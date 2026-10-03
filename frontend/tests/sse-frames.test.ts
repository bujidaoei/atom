import { test } from 'node:test';
import assert from 'node:assert/strict';
import { splitSseFrames } from '../src/workspace/sse-frames.ts';

test('parses a real run event across network chunks and ignores heartbeat', () => {
  const first = splitSseFrames('event: run\ndata: {"seq":1,"type":"message.delta"');
  assert.deepEqual(first.frames, []);
  const second = splitSseFrames(first.pending + ',"payload":{"text":"你好"}}\n\n: ping\n\n');
  assert.deepEqual(second.frames, [{ event: 'run', data: '{"seq":1,"type":"message.delta","payload":{"text":"你好"}}' }]);
  assert.equal(second.pending, '');
});

test('normalizes CRLF and joins multiple data lines', () => {
  const result = splitSseFrames('event: message\r\ndata: first\r\ndata: second\r\n\r\n');
  assert.deepEqual(result.frames, [{ event: 'message', data: 'first\nsecond' }]);
  assert.equal(result.pending, '');
});
