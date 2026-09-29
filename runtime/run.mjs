import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent } from "@earendil-works/pi-agent-core";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

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

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function viewOf(message) {
  const content = message?.content;
  if (typeof content === "string") return { text: content, thinking: "" };
  if (!Array.isArray(content)) return { text: "", thinking: "" };
  let text = "";
  let thinking = "";
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    if (block.type === "thinking") thinking += block.thinking || block.text || "";
    else if (block.type === "text") text += block.text || "";
  }
  return { text, thinking };
}

function toolText(result) {
  const blocks = Array.isArray(result?.content) ? result.content : [];
  return blocks
    .map((block) => (block && block.type === "text" ? String(block.text || "") : ""))
    .join("")
    .slice(0, 240);
}

function checkHtml(html, requirements) {
  const misses = [];
  for (const requirement of requirements) {
    for (const check of requirement.checks || []) {
      if (check.op === "exists") {
        const id = String(check.selector || "").replace(/^#/, "");
        if (id && !html.includes(`id="${id}"`) && !html.includes(`id='${id}'`)) {
          misses.push(`${requirement.key} 页面里没有 #${id}`);
        }
      } else if (check.op === "text" && check.contains && !html.includes(check.contains)) {
        misses.push(`${requirement.key} 页面上没有「${check.contains}」`);
      }
    }
  }
  return misses;
}

function buildTools(requirements) {
  const page = { html: "", notes: "", trace: "" };
  return {
    page,
    tools: [
      {
        name: "read_contract",
        label: "读取契约",
        description: "读取已经锁定的契约、检查项和架构说明。写页面前先调用。",
        parameters: Type.Object({}),
        async execute() {
          const brief = requirements
            .map((item) => `${item.key} ${item.title} ${(item.checks || []).map((check) => check.op).join(",")}`)
            .join("\n");
          return { content: [{ type: "text", text: brief || "没有契约" }], details: {} };
        },
      },
      {
        name: "write_page",
        label: "编写代码",
        description: "写入唯一的 index.html。html 必须是完整文档。",
        parameters: Type.Object({
          html: Type.String({ description: "完整 HTML 文档" }),
          notes: Type.String({ description: "两句中文说明" }),
          trace: Type.String({ description: "每条需求一行，格式 R1 | 证据" }),
        }),
        async execute(_id, args) {
          page.html = String(args.html || "");
          page.notes = String(args.notes || "");
          page.trace = String(args.trace || "");
          return { content: [{ type: "text", text: `已写入 index.html，${page.html.length} 个字符` }], details: {} };
        },
      },
      {
        name: "check_page",
        label: "检查页面",
        description: "检查刚才写入的页面是否包含契约要求的元素和正文。",
        parameters: Type.Object({}),
        async execute() {
          if (!page.html) return { content: [{ type: "text", text: "还没有页面" }], details: {} };
          const misses = checkHtml(page.html, requirements);
          const text = misses.length ? misses.join("；") : "通过";
          return { content: [{ type: "text", text }], details: {} };
        },
      },
    ],
  };
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
const mode = job.mode === "build" ? "build" : "speak";
const requirements = Array.isArray(job.requirements) ? job.requirements : [];
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

  const built = mode === "build" ? buildTools(requirements) : { page: { html: "", notes: "", trace: "" }, tools: [] };
  let lastText = "";
  let lastThinking = "";
  let textAt = 0;
  const agent = new Agent({
    initialState: {
      systemPrompt: system,
      model,
      thinkingLevel: "off",
      tools: built.tools,
    },
    streamFn: modelRuntime.streamSimple.bind(modelRuntime),
  });
  agent.subscribe((event) => {
    if (event.type === "message_update" && event.message?.role === "assistant") {
      const view = viewOf(event.message);
      const now = Date.now();
      if (view.thinking && view.thinking !== lastThinking && now - textAt > 180) {
        lastThinking = view.thinking;
        textAt = now;
        emit({ event: "thinking", text: view.thinking.slice(-500) });
      }
      if (view.text && view.text !== lastText && (now - textAt > 180 || view.text.length - lastText.length > 24)) {
        lastText = view.text;
        textAt = now;
        emit({ event: "text", text: view.text });
      }
    } else if (event.type === "tool_execution_start") {
      const detail = event.toolName === "write_page" ? "index.html" : event.toolName === "read_contract" ? "契约" : "";
      emit({ event: "tool", name: event.toolName, status: "start", detail });
    } else if (event.type === "tool_execution_end") {
      emit({
        event: "tool",
        name: event.toolName,
        status: event.isError ? "error" : "done",
        detail: toolText(event.result),
      });
    }
  });

  const timer = setTimeout(() => agent.abort(), mode === "build" ? 110000 : 54000);
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
  const misses = built.page.html ? checkHtml(built.page.html, requirements) : [];
  const usage = assistant.usage || {};
  emit({
    event: "done",
    text,
    html: built.page.html,
    notes: built.page.notes,
    trace: built.page.trace,
    checks: built.page.html ? (misses.length ? misses.join("；") : "通过") : "",
    model: modelId,
    prompt_tokens: Number(usage.input) || 0,
    completion_tokens: Number(usage.output) || 0,
  });
} catch (error) {
  fail(error instanceof Error ? error.message : "Pi agent 运行失败。");
} finally {
  await rm(authDir, { recursive: true, force: true });
}
