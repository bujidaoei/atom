import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "@earendil-works/pi-agent-core";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";

const PROVIDER = "atom-gateway";

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

function textOf(message) {
  const content = message?.content;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((block) => {
      if (typeof block === "string") return block;
      if (block && typeof block.text === "string") return block.text;
      return "";
    })
    .join("");
}

function promptFrom(messages) {
  const system = messages
    .filter((message) => message.role === "system")
    .map((message) => String(message.content || ""))
    .join("\n\n");
  const turns = messages
    .filter((message) => message.role !== "system")
    .map((message) =>
      message.role === "user" ? String(message.content || "") : `上一轮输出：\n${String(message.content || "")}`,
    )
    .join("\n\n");
  return { system, turns };
}

const raw = await new Promise((resolve, reject) => {
  const chunks = [];
  process.stdin.on("data", (chunk) => chunks.push(chunk));
  process.stdin.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
  process.stdin.on("error", reject);
});

let job;
try {
  job = JSON.parse(raw);
} catch {
  fail("Pi 运行时没有收到合法的任务。");
}

const baseUrl = String(job.baseUrl || "").replace(/\/$/, "");
const apiKey = String(job.apiKey || "");
const modelId = String(job.model || "");
const maxTokens = Number(job.maxTokens) || 900;
const messages = Array.isArray(job.messages) ? job.messages : [];
if (!baseUrl.startsWith("https://") || !apiKey || !modelId || messages.length === 0) {
  fail("Pi 运行时缺少网关地址、密钥、模型或消息。");
}

const { system, turns } = promptFrom(messages);
const authDir = await mkdtemp(join(tmpdir(), "atom-pi-"));

try {
  const modelRuntime = await ModelRuntime.create({
    authPath: join(authDir, "auth.json"),
    modelsPath: null,
    refreshOnCreate: false,
    allowModelNetwork: false,
  });
  modelRuntime.registerProvider(PROVIDER, {
    name: "Atom Gateway",
    baseUrl,
    apiKey,
    api: "openai-completions",
    authHeader: true,
    models: [
      {
        id: modelId,
        name: modelId,
        api: "openai-completions",
        // Qwen only receives enable_thinking when reasoning is on. Off means the flag is false.
        reasoning: true,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000,
        maxTokens,
        compat: {
          supportsDeveloperRole: false,
          supportsReasoningEffort: false,
          supportsStore: false,
          maxTokensField: "max_tokens",
          thinkingFormat: "qwen",
        },
      },
    ],
  });
  await modelRuntime.setRuntimeApiKey(PROVIDER, apiKey);
  const model = modelRuntime.getModel(PROVIDER, modelId);
  if (!model) fail(`网关上没有这个模型：${modelId}`);

  const agent = new Agent({
    initialState: {
      systemPrompt: system,
      model,
      thinkingLevel: "off",
      tools: [],
    },
    streamFn: modelRuntime.streamSimple.bind(modelRuntime),
  });

  const timer = setTimeout(() => agent.abort(), 54000);
  try {
    await agent.prompt(turns);
  } finally {
    clearTimeout(timer);
  }

  const assistant = [...agent.state.messages].reverse().find((message) => message.role === "assistant");
  if (!assistant) fail("Pi agent 没有返回内容。");
  if (assistant.stopReason === "aborted") fail("模型网关超时，Pi agent 已停止这一轮。");
  if (assistant.stopReason === "error") fail(assistant.errorMessage || "模型网关返回失败。");
  const text = textOf(assistant).trim();
  if (!text) fail("Pi agent 返回了空内容。");
  const usage = assistant.usage || {};
  process.stdout.write(
    `${JSON.stringify({
      text,
      model: modelId,
      prompt_tokens: Number(usage.input) || 0,
      completion_tokens: Number(usage.output) || 0,
    })}\n`,
  );
} catch (error) {
  fail(error instanceof Error ? error.message : "Pi agent 运行失败。");
} finally {
  await rm(authDir, { recursive: true, force: true });
}
