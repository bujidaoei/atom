/** Product routing is determined by the executing Waker, never by the message sender. */
export function resolveRegisteredWakerExecutionTarget(input: {
  environment: 'local' | 'cloud';
  deviceId: string | null;
}): 'local' | 'cloud' {
  if (input.environment === 'cloud') return 'cloud';
  if (!input.deviceId) throw new Error('Local Waker has no registered execution device');
  return 'local';
}
