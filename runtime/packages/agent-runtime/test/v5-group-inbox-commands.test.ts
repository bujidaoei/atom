import { describe, expect, it } from 'vitest';

import { parseV3GroupInboxCommand } from '../src/v3-group-messaging.ts';

describe('official Inbox CLI contract', () => {
  it('parses default, bounded and cursor claim forms in the current Conversation', () => {
    expect(
      parseV3GroupInboxCommand('qoderwake messages claim conversation --format user-message', 'conversation'),
    ).toEqual({ kind: 'claim', json: false });
    expect(
      parseV3GroupInboxCommand(
        'qoderwake messages claim conversation --limit 3 --cursor "cursor-value" --json',
        'conversation',
      ),
    ).toEqual({ kind: 'claim', limit: 3, cursor: 'cursor-value', json: true });
  });
  it('accepts exact repeated message flags and rejects the observed bare-second-id mistake', () => {
    expect(
      parseV3GroupInboxCommand(
        'qoderwake messages read conversation --claim claim --message first --message second',
        'conversation',
      ),
    ).toEqual({ kind: 'read', claimId: 'claim', messageIds: ['first', 'second'], json: false });
    expect(() =>
      parseV3GroupInboxCommand(
        'qoderwake messages read conversation --claim claim --message first second',
        'conversation',
      ),
    ).toThrow();
  });
  it.each([
    'qoderwake messages claim other',
    'qoderwake messages claim conversation --limit 51',
    'qoderwake messages claim conversation --limit 0',
    'qoderwake messages claim conversation --limit 3.5',
    'qoderwake messages read conversation --claim claim',
    'qoderwake messages claim conversation; echo forged',
    'qoderwake messages claim conversation\nwhoami',
    'qoderwake messages claim conversation --unknown yes',
  ])('fails closed without a delegated shell operation: %s', (command) => {
    expect(() => parseV3GroupInboxCommand(command, 'conversation')).toThrow();
  });
});
