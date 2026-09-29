/**
 * Client-side bounds for the existing status-first Feishu claim action.
 * These values are deliberately conservative: the server advertises a two
 * second retry and the UI must never remain busy indefinitely.
 */
export const V5_CLAIM_POLL_DEFAULT_DELAY_MS = 2_000 as const;
export const V5_CLAIM_POLL_MAX_WAIT_MS = 30_000 as const;
