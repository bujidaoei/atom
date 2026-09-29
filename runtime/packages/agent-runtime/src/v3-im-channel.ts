import type { V3CreateImChannel, V3ImChannel, V3UpdateImChannel } from '../../product-contracts/src/v3.ts';

export const V3_IM_CREDENTIAL_KEYS: Record<V3ImChannel['provider'], readonly string[]> = {
  dingtalk_bot: ['APP_KEY', 'APP_SECRET'],
  dingtalk_account: [],
  feishu: ['APP_ID', 'APP_SECRET'],
  wechat: [],
  wecom: ['ROBOT_ID', 'ROBOT_SECRET'],
  qq_bot: ['APP_ID', 'APP_SECRET'],
};

export function validateV3ImChannelConfiguration(input: V3CreateImChannel | V3UpdateImChannel): void {
  const required = V3_IM_CREDENTIAL_KEYS[input.provider];
  if (required.length === 0) {
    throw new Error(
      `${input.provider} requires its observed QR/account authorization flow, which is unavailable`,
    );
  }
  const supplied = Object.keys(input.credentials).sort();
  const expected = [...required].sort();
  const preservingExistingCredentials = 'expectedVersion' in input && supplied.length === 0;
  if (
    !preservingExistingCredentials &&
    (supplied.length !== expected.length || supplied.some((key, index) => key !== expected[index]))
  ) {
    throw new Error(`${input.provider} requires exactly these credential keys: ${expected.join(', ')}`);
  }
  if (input.provider === 'dingtalk_bot' && !input.cardType) {
    throw new Error('DingTalk Bot requires a card type');
  }
  if (input.provider !== 'dingtalk_bot' && input.cardType !== undefined) {
    throw new Error('Card type is only supported by DingTalk Bot');
  }
  if (input.accessPolicy === 'open_access' && !input.wakerId) {
    throw new Error('Open Access requires a default Waker');
  }
}
