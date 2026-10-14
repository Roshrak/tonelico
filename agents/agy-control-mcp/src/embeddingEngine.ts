import { existsSync } from "node:fs";
import fs from "node:fs/promises";
import { createHash } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { InferenceSession, Tensor, type InferenceSession as Session } from "onnxruntime-node";
import { Tokenizer } from "tokenizers";

export const EMBEDDING_MODEL_ID = "Xenova/multilingual-e5-small";
export const EMBEDDING_MODEL_REVISION = "761b726dd34fb83930e26aab4e9ac3899aa1fa78";
export const EMBEDDING_ONNX_FILE = "model_int8.onnx";
export const EMBEDDING_REVISION = "e5-small-int8-1.1.0";
export const EMBEDDING_DIMENSIONS = 384;
export const EMBEDDING_MAX_TOKENS = 512;
export const EMBEDDING_BATCH_SIZE = 24;

const MODEL_SHA256 = "4d24e2bc01a447951524466ef533e52944bf48509e6552810bcee1a2711cb02c";
const TOKENIZER_SHA256 = "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39";

function defaultModelDirectory(): string {
  return path.join(process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"), "agy-control-mcp", "models", "Xenova-multilingual-e5-small");
}

async function sha256(filePath: string): Promise<string> {
  return createHash("sha256").update(await fs.readFile(filePath)).digest("hex");
}

function meanPool(hiddenState: Float32Array, sequenceLength: number, dimensions: number, mask: BigInt64Array, row: number): Float32Array {
  const pooled = new Float32Array(dimensions!);
  let maskSum = 0;
  for (let token = 0; token < sequenceLength; token += 1) {
    const weight = Number(mask[token]);
    maskSum += weight;
    for (let dimension = 0; dimension < dimensions; dimension += 1) {
      pooled[dimension] += hiddenState[(row * sequenceLength + token) * dimensions + dimension] * weight;
    }
  }
  if (!maskSum) return pooled;
  let norm = 0;
  for (let dimension = 0; dimension < dimensions; dimension += 1) {
    pooled[dimension] /= maskSum;
    norm += pooled[dimension] ** 2;
  }
  norm = Math.sqrt(norm) || 1;
  for (let dimension = 0; dimension < dimensions; dimension += 1) pooled[dimension] /= norm;
  return pooled;
}

export class EmbeddingEngine {
  private tokenizer: Tokenizer | undefined;
  private session: Session | undefined;
  private loading: Promise<void> | undefined;
  private readonly modelDirectory: string;

  constructor(modelDirectory = process.env.AGY_EMBEDDING_MODEL_DIR || defaultModelDirectory()) {
    this.modelDirectory = path.resolve(modelDirectory);
  }

  static filesComplete(modelDirectory: string): boolean {
    return ["tokenizer.json", "model_int8.onnx"].every((file) => existsSync(path.join(modelDirectory, file)));
  }

  availability(): { enabled: boolean; model_id: string; revision: string; onnx_file: string; dimensions: number; model_directory: string; files_complete: boolean; reason?: string } {
    const complete = EmbeddingEngine.filesComplete(this.modelDirectory);
    return {
      enabled: complete, model_id: EMBEDDING_MODEL_ID, revision: EMBEDDING_MODEL_REVISION,
      onnx_file: EMBEDDING_ONNX_FILE, dimensions: EMBEDDING_DIMENSIONS,
      model_directory: this.modelDirectory, files_complete: complete,
      reason: complete ? undefined : "local ONNX/tokenizer model is absent; automatic download is disabled",
    };
  }

  private async load(): Promise<void> {
    if (this.tokenizer && this.session) return;
    this.loading ||= (async () => {
      const tokenizerPath = path.join(this.modelDirectory, "tokenizer.json");
      const modelPath = path.join(this.modelDirectory, "model_int8.onnx");
      if (!EmbeddingEngine.filesComplete(this.modelDirectory)) throw new Error("Embedding model is incomplete; automatic download is disabled");
      if (await sha256(tokenizerPath) !== TOKENIZER_SHA256) throw new Error("Embedding tokenizer checksum mismatch");
      if (await sha256(modelPath) !== MODEL_SHA256) throw new Error("Embedding ONNX checksum mismatch");
      this.tokenizer = Tokenizer.fromFile(tokenizerPath);
      this.session = await InferenceSession.create(modelPath, { executionProviders: ["cpu"] });
    })();
    try { await this.loading; }
    catch (error) { this.loading = undefined; throw error; }
  }

  async countTokens(text: string, kind: "query" | "passage" = "passage"): Promise<number> {
    await this.load();
    const encoding = await this.tokenizer!.encode(`${kind}: ${text.replace(/\s+/g, " ").trim()}`, undefined, { addSpecialTokens: true });
    return encoding.getLength();
  }

  private async embedMany(inputs: string[], signal?: AbortSignal): Promise<Float32Array[]> {
    await this.load();
    const encodings = await this.tokenizer!.encodeBatch(inputs.map((text) => text), { addSpecialTokens: true });
    if (encodings.some((encoding) => encoding.getLength() > EMBEDDING_MAX_TOKENS)) {
      throw new Error(`Embedding input exceeds ${EMBEDDING_MAX_TOKENS} tokens; chunk it before embedding`);
    }
    const outputs: Float32Array[] = [];
    for (let start = 0; start < encodings.length; start += EMBEDDING_BATCH_SIZE) {
      signal?.throwIfAborted?.();
      const batch = encodings.slice(start, start + EMBEDDING_BATCH_SIZE);
      const sequenceLength = Math.max(...batch.map((encoding) => encoding.getLength()));
      const ids = new BigInt64Array(batch.length * sequenceLength);
      const attentionMask = new BigInt64Array(batch.length * sequenceLength);
      const tokenTypeIds = new BigInt64Array(batch.length * sequenceLength);
      for (const [row, encoding] of batch.entries()) {
        const rowIds = encoding.getIds();
        const rowMask = encoding.getAttentionMask();
        const rowTypes = encoding.getTypeIds();
        for (let token = 0; token < rowIds.length; token += 1) {
          const offset = row * sequenceLength + token;
          ids[offset] = BigInt(rowIds[token]!);
          attentionMask[offset] = BigInt(rowMask[token]!);
          tokenTypeIds[offset] = BigInt(rowTypes[token] || 0);
        }
      }
      const feeds: Record<string, Tensor> = {
        input_ids: new Tensor("int64", ids, [batch.length, sequenceLength]),
        attention_mask: new Tensor("int64", attentionMask, [batch.length, sequenceLength]),
        token_type_ids: new Tensor("int64", tokenTypeIds, [batch.length, sequenceLength]),
      };
      const output = await this.session!.run(feeds);
      const first = this.session!.outputNames[0];
      const tensor = output[first];
      const dimensions = Number(tensor.dims[2]);
      for (let row = 0; row < batch.length; row += 1) {
        outputs.push(meanPool(tensor.data as Float32Array, sequenceLength, dimensions, attentionMask.subarray(row * sequenceLength, (row + 1) * sequenceLength), row));
      }
    }
    return outputs;
  }

  async embedPassages(texts: string[], signal?: AbortSignal): Promise<Float32Array[]> {
    if (!texts.length) return [];
    return await this.embedMany(texts.map((text) => `passage: ${text.replace(/\s+/g, " ").trim()}`), signal);
  }

  async embedQuery(query: string): Promise<Float32Array> {
    const [vector] = await this.embedMany([`query: ${query.replace(/\s+/g, " ").trim()}`]);
    return vector!;
  }
}
