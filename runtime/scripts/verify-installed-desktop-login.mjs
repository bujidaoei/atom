/* global window */
import { execFileSync } from 'node:child_process';
import { _electron as electron } from 'playwright';
import { readFile, writeFile } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
const executablePath = process.env.DESKTOP_LOGIN_TEST_EXECUTABLE;
const key = process.env.DESKTOP_LOGIN_TEST_KEY;
const profilePath = process.env.DESKTOP_LOGIN_TEST_PROFILE;
const verifyInference = process.env.DESKTOP_LOGIN_TEST_INFERENCE === '1';
if (verifyInference && !profilePath) throw new Error('Inference acceptance requires an isolated QA profile');
if (profilePath) {
  const distance = relative(resolve('.tmp'), profilePath);
  if (!isAbsolute(profilePath) || !distance || distance.startsWith('..') || isAbsolute(distance)) {
    throw new Error('QA profile must be a dedicated directory inside workspace .tmp');
  }
}
const args = profilePath ? [`--user-data-dir=${profilePath}`] : [];
const expectedVersion = JSON.parse(await readFile('apps/desktop/package.json', 'utf8')).version;
if (!executablePath || !key) throw new Error('Installed executable and test key are required');
const environment = { ...process.env };
for (const name of Object.keys(environment))
  if (/^(WORKDUDE_|DESKTOP_|TEST_|TOKEN_|LITELLM_|FEISHU_|APP_)/.test(name)) delete environment[name];
delete environment.ELECTRON_RUN_AS_NODE;
environment.WORKDUDE_AUTOMATION_WINDOW = 'hidden';
let application;
const results = { version: '', port: 0, invalidKeyRejected: false, authenticated: false, restored: false };
const pageErrors = [];
await writeFile(
  '.tmp/installed-login-result.json',
  JSON.stringify({ status: 'running', startedAt: new Date().toISOString() }) + '\n',
);
try {
  application = await electron.launch({ executablePath, args, env: environment, timeout: 60000 });
  if (profilePath && (await application.evaluate(({ app }) => app.getPath('userData'))) !== profilePath) {
    throw new Error('Installed application did not honor its isolated QA profile');
  }
  results.version = await application.evaluate(({ app }) => app.getVersion());
  if (results.version !== expectedVersion)
    throw new Error('Installed version does not match current Desktop package');
  const page = await application.firstWindow({ timeout: 60000 });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 1536, height: 864 });
  page.setDefaultTimeout(45000);
  await page.waitForFunction(() => Boolean(window.workdude?.auth));
  if ((await page.evaluate(() => window.workdude.auth.mode)) !== 'api-key')
    throw new Error('Packaged default authentication is not API Key mode');
  if (await page.evaluate(async () => (await window.workdude.auth.getSession()).authenticated)) {
    await page.evaluate(() => window.workdude.auth.logout());
    await page.reload();
  }
  await page.getByRole('heading', { name: '登录 QoderWake', exact: true }).waitFor();
  const pid = await application.evaluate(() => process.pid);
  const boundPorts = JSON.parse(
    execFileSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        `@(Get-NetTCPConnection -State Listen -OwningProcess ${pid} | Select-Object -ExpandProperty LocalPort) | ConvertTo-Json -Compress`,
      ],
      { encoding: 'utf8', windowsHide: true },
    ),
  );
  for (const port of [boundPorts].flat()) {
    const response = await globalThis
      .fetch(`http://127.0.0.1:${port}/management`, {
        signal: globalThis.AbortSignal.timeout(1500),
      })
      .catch(() => undefined);
    if (response?.status === 401) {
      results.port = port;
      break;
    }
  }
  if (!results.port || results.port === 19820 || (!profilePath && results.port !== 19880)) {
    throw new Error('Product did not bind the expected loopback port');
  }
  await page.getByLabel('管理员 API Key', { exact: true }).fill('invalid-login-key-for-regression');
  await page.getByRole('button', { name: '使用管理员 API Key 登录', exact: true }).click();
  await page.getByText('管理员 API Key 不正确，请检查输入内容后重试。', { exact: true }).waitFor();
  results.invalidKeyRejected = true;
  await page.getByLabel('管理员 API Key', { exact: true }).fill(key);
  await page.getByRole('button', { name: '使用管理员 API Key 登录', exact: true }).click();
  await page.getByRole('heading', { name: 'Waker 管理', exact: true }).waitFor();
  results.authenticated = await page.evaluate(async () =>
    Boolean((await window.workdude.auth.getSession()).authenticated),
  );
  await page.getByRole('link', { name: '@Waker', exact: true }).click();
  const navigationMask = await page
    .getByRole('link', { name: '@Waker', exact: true })
    .locator('span[style]')
    .evaluate((element) => globalThis.getComputedStyle(element).maskImage);
  if (navigationMask === 'none') throw new Error('@Waker navigation SVG mask was rejected');
  const filters = await page.locator('.qc-at-waker-list-filter').evaluateAll((elements) =>
    elements.map((element) => ({
      width: element.getBoundingClientRect().width,
      height: element.getBoundingClientRect().height,
      valueHeight: element.querySelector('.qc-at-waker-list-filter__value').getBoundingClientRect().height,
    })),
  );
  if (
    filters.length !== 3 ||
    filters.some(
      (filter, index) =>
        filter.width !== [192, 160, 134][index] || filter.height !== 32 || filter.valueHeight !== 20,
    )
  ) {
    throw new Error('Installed @Waker filters do not match the observed single-line layout');
  }
  await page.getByRole('combobox', { name: '状态', exact: true }).click();
  await page.getByRole('option', { name: '连接已删除', exact: true }).click();
  if (!(await page.getByRole('combobox', { name: '状态', exact: true }).innerText()).includes('连接已删除'))
    throw new Error('Status selection was not reflected in its trigger');
  await page.getByRole('combobox', { name: '状态', exact: true }).click();
  await page.getByRole('option', { name: '全部', exact: true }).click();
  await page.getByRole('tab', { name: /^Group（/ }).click();
  const groupPage = page.url();
  await page.getByRole('button', { name: '新建 Group', exact: true }).click();
  await page.getByRole('dialog', { name: '创建群组', exact: true }).waitFor();
  if (page.url() !== groupPage) throw new Error('New Group navigated away from its current page');
  await page.screenshot({ path: resolve('.tmp/installed-group-dialog-verified.png'), scale: 'css' });
  await page.getByRole('button', { name: '取消', exact: true }).click();
  const motionWidths = [];
  for (let sample = 0; sample < 36; sample += 1) {
    motionWidths.push(
      await page.locator('.qc-at-waker-hero-scene__typing').evaluate((element) => {
        if (globalThis.getComputedStyle(element).animationDuration !== '16.8s')
          throw new Error('Incorrect hero cycle');
        return element.getBoundingClientRect().width;
      }),
    );
    await page.waitForTimeout(500);
  }
  if (!motionWidths.some((width) => width <= 1) || !motionWidths.some((width) => width > 100))
    throw new Error('Installed hero animation did not visibly cycle');
  results.filters = filters;
  results.groupDialog = true;
  results.motionCycle = true;
  await page.screenshot({ path: resolve('.tmp/installed-at-waker-verified.png'), scale: 'css' });
  await page.getByRole('tab', { name: /^Waker（/ }).click();
  await page.getByRole('link', { name: 'Waker 管理', exact: true }).click();
  await page.getByRole('heading', { name: 'Waker 管理', exact: true }).waitFor();
  if (verifyInference) {
    const wakerName = `Desktop acceptance ${Date.now()}`;
    await page.getByRole('button', { name: '新建 Waker', exact: true }).first().click();
    await page.getByRole('heading', { name: '创建 Waker', exact: true }).waitFor();
    await page.screenshot({ path: resolve('.tmp/installed-recruitment-verified.png'), scale: 'css' });
    await page.getByRole('button', { name: '查看 后端工程师 的详情', exact: true }).click();
    await page.screenshot({ path: resolve('.tmp/installed-role-detail-verified.png'), scale: 'css' });
    await page.getByRole('button', { name: '就他了！', exact: true }).click();
    await page.getByPlaceholder('请输入 Waker 名称', { exact: true }).fill(wakerName);
    await page.screenshot({ path: resolve('.tmp/installed-creation-verified.png'), scale: 'css' });
    await page.getByRole('button', { name: '创建', exact: true }).click();
    await page.getByRole('button', { name: '直接对话', exact: true }).click();
    await page
      .locator('.qc-composer-editor[contenteditable="true"]')
      .fill('请只回复 DESKTOP_PI_OK，不要调用工具或修改文件。');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByText('DESKTOP_PI_OK', { exact: true }).waitFor({ timeout: 180000 });
    results.inference = true;
    results.wakerName = wakerName;
    await page.screenshot({ path: resolve('.tmp/installed-inference-verified.png'), scale: 'css' });
  }
  await page.screenshot({ path: resolve('.tmp/installed-login-verified.png'), scale: 'css' });
  await application.close();
  application = undefined;
  application = await electron.launch({ executablePath, args, env: environment, timeout: 60000 });
  const resumed = await application.firstWindow({ timeout: 60000 });
  resumed.on('pageerror', (error) => pageErrors.push(error.message));
  resumed.setDefaultTimeout(45000);
  await resumed.getByRole('heading', { name: 'Waker 管理', exact: true }).waitFor();
  results.restored = await resumed.evaluate(async () =>
    Boolean((await window.workdude.auth.getSession()).authenticated),
  );
  if (!results.authenticated || !results.restored) throw new Error('Session acceptance failed');
  if (pageErrors.length) throw new Error(`Desktop page errors: ${pageErrors.join('; ')}`);
  if (verifyInference) {
    const database = new DatabaseSync(resolve(profilePath, 'workdude-v3.sqlite'), { readOnly: true });
    try {
      const run = database
        .prepare('SELECT id,status,model,result_text FROM v3_runs ORDER BY created_at DESC LIMIT 1')
        .get();
      if (run?.status !== 'completed' || !run.result_text?.includes('DESKTOP_PI_OK')) {
        throw new Error('The real Pi run was not durably completed');
      }
      results.runId = run.id;
      results.model = run.model;
      results.persistedReply = true;
    } finally {
      database.close();
    }
  }
  await writeFile(
    '.tmp/installed-login-result.json',
    JSON.stringify({ status: 'passed', ...results }, null, 2) + '\n',
  );
  console.log(JSON.stringify(results));
} catch (error) {
  console.error(String(error).replaceAll(key, '[REDACTED]'));
  await writeFile(
    '.tmp/installed-login-result.json',
    JSON.stringify(
      { status: 'failed', ...results, error: String(error).replaceAll(key, '[REDACTED]') },
      null,
      2,
    ) + '\n',
  );
  const page = await application?.firstWindow().catch(() => undefined);
  if (page) {
    await page.screenshot({ path: resolve('.tmp/installed-acceptance-failed.png') }).catch(() => undefined);
    await writeFile(
      '.tmp/installed-acceptance-failed.txt',
      (await page.locator('body').innerText()).replaceAll(key, '[REDACTED]'),
    ).catch(() => undefined);
  }
  process.exitCode = 1;
} finally {
  await application?.close();
}
