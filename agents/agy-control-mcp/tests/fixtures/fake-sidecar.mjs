// Fake PhoWhisper sidecar used by tests to exercise the persistent-process protocol
// without a GPU or the real Python worker. Behaviour is selected with FAKE_SIDECAR_MODE.
import { basename } from "node:path";
import readline from "node:readline";

const mode = process.env.FAKE_SIDECAR_MODE || "ok";
const out = (event) => process.stdout.write(`${JSON.stringify(event)}\n`);

out({ event: "ready", protocol_version: 1, model_id: "PhoWhisper-large-ct2", model_revision: "test-1" });

const rl = readline.createInterface({ input: process.stdin, terminal: false });
let activeCancelToken;
let cancelled = false;

rl.on("line", (line) => {
  let request;
  try { request = JSON.parse(line); } catch { return; }
  const { id, type } = request;
  if (type === "health") {
    out({ id, event: "result", ok: true, protocol_version: 1, model_id: "PhoWhisper-large-ct2", model_revision: "test-1", model_files_complete: true });
    return;
  }
  if (type === "cancel") {
    if (activeCancelToken === request.cancel_token) cancelled = true;
    out({ id, event: "result", ok: true, status: "cancelling", cancel_token: request.cancel_token });
    return;
  }
  if (type === "shutdown") {
    out({ id, event: "result", ok: true, status: "shutdown" });
    setTimeout(() => process.exit(0), 25);
    return;
  }
  if (type !== "transcribe") return;

  const token = `${id}-token`;
  activeCancelToken = token;
  cancelled = false;
  out({ id, event: "accepted", ok: true, status: "queued", cancel_token: token });

  // A file whose basename starts with "boom" triggers a mid-job crash (no result, process dies)
  // so restart tests stay deterministic regardless of when the child was spawned.
  if (/^boom/i.test(basename(String(request.audio_path)))) {
    setTimeout(() => process.exit(1), 30);
    return;
  }
  if (mode === "invalid_ndjson") {
    setTimeout(() => { process.stdout.write("this is not json\n"); }, 20);
    return;
  }
  if (mode === "reject") {
    setTimeout(() => out({ id, event: "error", ok: false, status: "error", error: "Audio stream contains no audio track" }), 20);
    return;
  }
  if (mode === "slow_cancelable") {
    // Stay busy until the JSONL cancel arrives, then honour it like the real engine.
    const poll = setInterval(() => {
      if (!cancelled) return;
      clearInterval(poll);
      out({ id, event: "error", ok: false, status: "cancelled", cancel_token: token, error: "cancelled by request" });
    }, 15);
    return;
  }
  setTimeout(() => out({
    id, event: "result", ok: true, status: "done", cancel_token: token,
    language: "vi", audio_duration_ms: 2500, processing_time_ms: 10,
    segments: [
      { start_ms: 0, end_ms: 1250, text: "Xin chào bác sĩ" },
      { start_ms: 1250, end_ms: 2500, text: "Cơn đau tăng về đêm" },
    ],
    text: "Xin chào bác sĩ. Cơn đau tăng về đêm.",
  }), mode === "slow" ? 300 : 20);
});
