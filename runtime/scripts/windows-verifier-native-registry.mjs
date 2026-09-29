import { execFile as execFileCallback, spawn } from 'node:child_process';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { promisify } from 'node:util';

const execFile = promisify(execFileCallback);
const browserNativeRegistryKey =
  'Software\\Google\\Chrome\\NativeMessagingHosts\\com.workdude.browser_connector';

const powershellLiteral = (value) => `'${value.replaceAll("'", "''")}'`;

export const readExistingBrowserNativeManifest = async () => {
  const script =
    `$ErrorActionPreference='Stop';$key=${powershellLiteral(browserNativeRegistryKey)};` +
    `if(-not(Test-Path -LiteralPath "HKCU:\\$key")){ 'absent'; exit 0 };` +
    `$value=(Get-ItemProperty -LiteralPath "HKCU:\\$key" -Name '(default)').'(default)';` +
    `if($null -eq $value){ 'empty' } else { [string]$value }`;
  const { stdout } = await execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    windowsHide: true,
    timeout: 10_000,
    maxBuffer: 16 * 1024,
  });
  const value = stdout.trim();
  return value === 'absent' ? undefined : value;
};

export const cleanupVerifierOwnedBrowserNativeRegistry = async (userData, baselineManifestPath) => {
  const expectedManifest = join(userData, 'browser-connector-native-host.json');
  const baseline = baselineManifestPath === undefined ? '$null' : powershellLiteral(baselineManifestPath);
  const script =
    `$ErrorActionPreference='Stop';$subKey=${powershellLiteral(browserNativeRegistryKey)};` +
    `$expected=${powershellLiteral(expectedManifest)};` +
    `$baseline=${baseline};` +
    `$key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey($subKey,$true);` +
    `if($null-eq$key){if($null-eq$baseline){'absent';exit 0}else{exit 5}};` +
    `try{$names=@($key.GetValueNames());$children=@($key.GetSubKeyNames());` +
    `$value=[string]$key.GetValue('', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames);` +
    `if($names.Count-ne 1-or$names[0]-ne''-or$children.Count-ne 0){exit 4};` +
    `if($null-ne$baseline-and$value.Equals($baseline,[StringComparison]::OrdinalIgnoreCase)){'preserved';exit 0};` +
    `if(-not$value.Equals($expected,[StringComparison]::OrdinalIgnoreCase)){exit 4}}finally{$key.Dispose()};` +
    `if($null-ne$baseline){$key=[Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($subKey);try{$key.SetValue('', $baseline, [Microsoft.Win32.RegistryValueKind]::String)}finally{$key.Dispose()};'restored'}else{[Microsoft.Win32.Registry]::CurrentUser.DeleteSubKeyTree($subKey,$false);'removed'}`;
  const cleanup = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let cleanupOutput = '';
  let cleanupError = '';
  cleanup.stdout.setEncoding('utf8');
  cleanup.stderr.setEncoding('utf8');
  cleanup.stdout.on('data', (chunk) => (cleanupOutput += chunk));
  cleanup.stderr.on('data', (chunk) => (cleanupError += chunk));
  const cleanupExit = await Promise.race([
    new Promise((resolveExit, rejectExit) => {
      cleanup.once('error', rejectExit);
      cleanup.once('exit', (code, signal) => resolveExit({ code, signal }));
    }),
    delay(10_000, null),
  ]);
  if (cleanupExit === null) {
    cleanup.kill();
    throw new Error('Verifier-owned Browser Native registry cleanup exceeded 10 seconds.');
  }
  const result = cleanupOutput.trim();
  if (
    cleanupExit.code !== 0 ||
    (result !== 'removed' && result !== 'absent' && result !== 'preserved' && result !== 'restored')
  ) {
    throw new Error(
      `Verifier-owned Browser Native registry cleanup failed (${String(cleanupExit.code ?? cleanupExit.signal)}): ${cleanupError.slice(-2_000)}`,
    );
  }
};
