import { fork } from 'node:child_process';
import { Buffer } from 'node:buffer';
import { mkdtemp, writeFile, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createServer } from 'node:http';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { setTimeout, clearTimeout } from 'node:timers';

// Exercises production ASAR code in its packaged Electron runtime. This is a
// backend integration gate, not native-window or installer acceptance.
if (process.platform !== 'win32') throw new Error('This gate requires Windows.');
const root = await mkdtemp(resolve('.tmp/email-package-'));
const wrapper = join(root, 'bridge.mjs');
const entry = resolve(
  'apps/desktop/out/QoderWake-win32-x64/resources/app.asar/.vite/build/local-agent-host.mjs',
);
await writeFile(
  wrapper,
  `process.parentPort={postMessage:m=>process.send(m),on:(_e,f)=>process.on('message',data=>{if(data.payload?.method==='addKnowledgeFileMaterial')data.payload.input.value.bytes=new Uint8Array(data.payload.input.value.bytes);f({data})})};\nawait import(${JSON.stringify(pathToFileURL(entry).href)});\nprocess.send({ready:true});`,
);
const child = fork(wrapper, [], {
  execPath: resolve('apps/desktop/out/QoderWake-win32-x64/QoderWake.exe'),
  execArgv: [],
  env: {
    ...Object.fromEntries(
      Object.entries(process.env).filter(([name]) =>
        ['path', 'systemroot', 'windir', 'temp', 'tmp', 'userprofile', 'localappdata', 'appdata'].includes(
          name.toLowerCase(),
        ),
      ),
    ),
    ELECTRON_RUN_AS_NODE: '1',
  },
  serialization: 'json',
  silent: true,
  windowsHide: true,
});
let logs = '';
child.stderr.on('data', (b) => {
  logs = (logs + b).slice(-4000);
});
const ready = new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error(`Packaged host startup timeout: ${logs}`)), 30000);
  child.on('message', (message) => {
    if (message.ready) {
      clearTimeout(timer);
      resolve();
    }
  });
  child.once('error', (error) => {
    clearTimeout(timer);
    reject(error);
  });
  child.once('exit', (code) => {
    clearTimeout(timer);
    reject(new Error(`Packaged host exited ${code}: ${logs}`));
  });
});
let id = 0;
const pending = new Map();
child.on('message', (m) => {
  const p = pending.get(m.id);
  if (p) {
    pending.delete(m.id);
    if (m.ok) p.resolve(m.result);
    else p.reject(new Error(m.error));
  }
});
const call = (method, payload) =>
  new Promise((resolve, reject) => {
    const key = String(++id);
    const timer = setTimeout(() => {
      pending.delete(key);
      reject(new Error(`RPC timeout ${method}: ${logs.slice(-1000)}`));
    }, 30000);
    pending.set(key, {
      resolve: (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      reject: (e) => {
        clearTimeout(timer);
        reject(e);
      },
    });
    child.send({ type: 'rpc-request', id: key, method, payload });
  });
const invoke = (method, input) => call('v3Product', { method, input });
const waitForMaterials = async (knowledgeBaseId, expectedCount) => {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    const materials = await invoke('listKnowledgeMaterials', {
      knowledgeBaseId,
      page: { limit: 50 },
    });
    if (
      materials.items.length === expectedCount &&
      materials.items.every((item) => item.processingState === 'ready')
    ) {
      return materials;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Packaged Knowledge processing did not finish: ${logs.slice(-1000)}`);
};
let bootstrap;
let completions = 0;
const server = createServer(async (req, res) => {
  for await (const chunk of req) {
    void chunk;
  }
  res.setHeader('content-type', 'application/json');
  if (req.url === '/api/v3/bootstrap') {
    res.end(
      JSON.stringify({ ...bootstrap, aiGatewayModel: 'deepseek-chat', aiGatewayModels: ['deepseek-chat'] }),
    );
    return;
  }
  if (req.url === '/api/v3/ai-gateway/chat/completions') {
    completions++;
    res.end(
      JSON.stringify({
        id: 'synthetic',
        choices: [
          {
            message: {
              role: 'assistant',
              content: JSON.stringify({
                cards: [
                  {
                    title: 'Packaged email',
                    keywords: ['email'],
                    contentMarkdown: '## Evidence\n\nPackaged MIME source.',
                  },
                ],
              }),
            },
            finish_reason: 'stop',
          },
        ],
        usage: { prompt_tokens: 2, completion_tokens: 3, total_tokens: 5 },
      }),
    );
    return;
  }
  res.statusCode = 404;
  res.end('{}');
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
try {
  await ready;
  const seed = {
    dataDir: join(root, 'profile'),
    configuration: { platformOrigin: '', platformAccessToken: '', aiGatewayModel: '' },
    automationAccessToken: 'synthetic-automation-token-at-least-32-chars',
    resourceEncryptionKey: 'r'.repeat(43),
  };
  await call('initialize', seed);
  bootstrap = await invoke('bootstrap');
  await call('shutdown');
  const configured = {
    ...seed,
    configuration: {
      platformOrigin: `http://127.0.0.1:${server.address().port}`,
      platformAccessToken: 'synthetic-platform-token',
      aiGatewayModel: 'deepseek-chat',
    },
  };
  await call('initialize', configured);
  const base = await invoke('createKnowledgeBase', {
    value: { name: 'Packaged email', description: '' },
    idempotencyKey: 'packaged-email-base',
  });
  const input = {
    knowledgeBaseId: base.id,
    value: {
      fileName: 'knowledge-email.eml',
      mediaType: 'message/rfc822',
      bytes: Array.from(await readFile('tests/fixtures/v5/knowledge-email.eml')),
      parentFolderId: null,
    },
    idempotencyKey: 'packaged-email-import',
  };
  const material = await invoke('addKnowledgeFileMaterial', input);
  assert.equal(material.processingState, 'queued');
  const children = await waitForMaterials(base.id, 2);
  const content = await invoke('getKnowledgeMaterialContent', {
    knowledgeBaseId: base.id,
    materialId: material.id,
  });
  assert.equal(content.email.subject, '知识库邮件验收 0925');
  assert.equal(content.email.attachmentCount, 1);
  assert.match(content.compiledText, /EMAIL-BODY-0925/);
  assert.equal(children.items.length, 2);
  assert.ok(children.items.every((m) => m.processingState === 'ready'));
  assert.equal((await invoke('addKnowledgeFileMaterial', input)).id, material.id);
  assert.equal(completions, 2);
  const unsupportedBytes = Buffer.from(
    Buffer.from(input.value.bytes)
      .toString()
      .replaceAll('synthetic-attachment.txt', 'synthetic-attachment.bin'),
  );
  const bodyOnly = await invoke('addKnowledgeFileMaterial', {
    ...input,
    idempotencyKey: 'packaged-unsupported-import',
    value: { ...input.value, bytes: Array.from(unsupportedBytes) },
  });
  assert.equal(bodyOnly.parentFolderId, null);
  assert.equal(bodyOnly.processingState, 'queued');
  await waitForMaterials(base.id, 3);
  const bodyOnlyContent = await invoke('getKnowledgeMaterialContent', {
    knowledgeBaseId: base.id,
    materialId: bodyOnly.id,
  });
  assert.equal(bodyOnlyContent.email.attachmentCount, 0);
  assert.equal(completions, 3);
  await call('shutdown');
  await call('initialize', configured);
  const restored = await invoke('getKnowledgeMaterialContent', {
    knowledgeBaseId: base.id,
    materialId: material.id,
  });
  assert.equal(restored.email.subject, content.email.subject);
  console.log(
    JSON.stringify({
      passed: true,
      artifact: entry,
      asarSha256: createHash('sha256')
        .update(await readFile(resolve('apps/desktop/out/QoderWake-win32-x64/resources/app.asar')))
        .digest('hex'),
      checks: [
        'packaged Electron runtime',
        'MIME parser',
        'HTML sanitizer',
        'local persistence',
        'body and attachment compilation',
        'idempotent replay',
        'host restart',
        'unsupported attachment body-only import',
      ],
      completions,
      profile: root,
    }),
  );
} finally {
  await call('shutdown').catch(() => {});
  child.kill();
  server.closeAllConnections();
  await new Promise((r) => server.close(r));
}
