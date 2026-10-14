import fs from "node:fs/promises";
import path from "node:path";
import type { ControlConfig } from "./config.js";
import type { ResolvedTier } from "./types.js";

// Thrown when a slot never became free within the wait window. This means the backend was busy, not that
// the work failed, so schedulers should requeue it without spending one of the task's attempts.
export class CapacityWaitTimeout extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CapacityWaitTimeout";
  }
}

class Semaphore {
  private active = 0;
  private readonly queue: Array<{
    resolve: () => void;
    reject: (error: Error) => void;
    cancelled: () => boolean;
  }> = [];

  constructor(private readonly limit: number) {}

  async acquire(timeoutMilliseconds: number, cancelled: () => boolean): Promise<void> {
    if (cancelled()) throw new Error("Capacity acquisition cancelled");
    if (this.active < this.limit) {
      this.active += 1;
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const waiter = { resolve, reject, cancelled };
      this.queue.push(waiter);
      const remove = () => {
        const index = this.queue.indexOf(waiter);
        if (index >= 0) this.queue.splice(index, 1);
      };
      const timeout = setTimeout(() => {
        remove();
        waiter.reject(new CapacityWaitTimeout("Timed out waiting for in-process capacity"));
      }, Math.max(1, timeoutMilliseconds));
      const cancellation = setInterval(() => {
        if (!cancelled()) return;
        remove();
        waiter.reject(new Error("Capacity acquisition cancelled"));
      }, 50);
      const settle = (operation: () => void) => {
        clearTimeout(timeout);
        clearInterval(cancellation);
        operation();
      };
      waiter.resolve = () => settle(resolve);
      waiter.reject = (error) => settle(() => reject(error));
    });
  }

  release(): void {
    while (this.queue.length) {
      const waiter = this.queue.shift()!;
      if (waiter.cancelled()) {
        waiter.reject(new Error("Capacity acquisition cancelled"));
        continue;
      }
      // Reserve the active slot for the waiter before waking it. Decrementing first would let a
      // newly arriving caller overtake the queued waiter and temporarily exceed the limit.
      waiter.resolve();
      return;
    }
    this.active = Math.max(0, this.active - 1);
  }
}

async function readOwnerPid(slot: string): Promise<number | undefined> {
  try {
    const owner = JSON.parse(await fs.readFile(path.join(slot, "owner.json"), "utf8")) as { pid?: unknown };
    return Number.isInteger(owner.pid) && (owner.pid as number) > 0 ? (owner.pid as number) : undefined;
  } catch {
    return undefined;
  }
}

// A slot whose owner process has exited (crash, client restart, Ctrl-C) must not keep blocking the others.
function processAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export class CapacityController {
  private readonly tierSemaphores: Record<ResolvedTier, Semaphore>;
  private readonly globalSemaphore: Semaphore;

  constructor(private readonly config: ControlConfig) {
    this.tierSemaphores = {
      fast: new Semaphore(config.concurrency.fast),
      reasoning: new Semaphore(config.concurrency.reasoning),
      expert: new Semaphore(config.concurrency.expert),
    };
    this.globalSemaphore = new Semaphore(config.globalConcurrency);
  }

  private async acquireFilesystemSlot(name: string, limit: number, deadline: number, cancelled: () => boolean): Promise<() => Promise<void>> {
    const root = path.join(this.config.lockRoot, name);
    await fs.mkdir(root, { recursive: true });
    while (Date.now() < deadline) {
      if (cancelled()) throw new Error("Capacity acquisition cancelled");
      for (let index = 0; index < limit; index += 1) {
        const slot = path.join(root, String(index));
        try {
          await fs.mkdir(slot);
          await fs.writeFile(path.join(slot, "owner.json"), JSON.stringify({
            pid: process.pid,
            created_at: new Date().toISOString(),
          }), "utf8");
          return async () => {
            await fs.rm(slot, { recursive: true, force: true });
          };
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
          const stats = await fs.stat(slot).catch(() => undefined);
          const owner = await readOwnerPid(slot);
          const ownerDead = owner !== undefined && !processAlive(owner);
          const expired = stats !== undefined && Date.now() - stats.mtimeMs > (this.config.maxTimeoutSeconds + 120) * 1000;
          if (ownerDead || expired) {
            await fs.rm(slot, { recursive: true, force: true }).catch(() => undefined);
          }
        }
      }
      await sleep(100);
    }
    throw new CapacityWaitTimeout(`Timed out waiting for shared ${name} capacity`);
  }

  async acquire(tier: ResolvedTier, timeoutSeconds: number, cancelled: () => boolean = () => false): Promise<() => Promise<void>> {
    const deadline = Date.now() + Math.min(timeoutSeconds, 60) * 1000;
    await this.globalSemaphore.acquire(deadline - Date.now(), cancelled);
    let tierAcquired = false;
    let globalFilesystemRelease: (() => Promise<void>) | undefined;
    let tierFilesystemRelease: (() => Promise<void>) | undefined;
    try {
      await this.tierSemaphores[tier].acquire(deadline - Date.now(), cancelled);
      tierAcquired = true;
      globalFilesystemRelease = await this.acquireFilesystemSlot("global", this.config.globalConcurrency, deadline, cancelled);
      tierFilesystemRelease = await this.acquireFilesystemSlot(`tier-${tier}`, this.config.concurrency[tier], deadline, cancelled);
      let released = false;
      return async () => {
        if (released) return;
        released = true;
        await tierFilesystemRelease?.();
        await globalFilesystemRelease?.();
        this.tierSemaphores[tier].release();
        this.globalSemaphore.release();
      };
    } catch (error) {
      await tierFilesystemRelease?.();
      await globalFilesystemRelease?.();
      if (tierAcquired) this.tierSemaphores[tier].release();
      this.globalSemaphore.release();
      throw error;
    }
  }
}

const sharedControllers = new Map<string, CapacityController>();

export function sharedCapacityController(config: ControlConfig): CapacityController {
  const key = JSON.stringify({
    lockRoot: path.resolve(config.lockRoot).toLowerCase(),
    global: config.globalConcurrency,
    concurrency: config.concurrency,
  });
  const existing = sharedControllers.get(key);
  if (existing) return existing;
  const created = new CapacityController(config);
  sharedControllers.set(key, created);
  return created;
}
