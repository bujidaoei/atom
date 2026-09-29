import { Buffer } from 'node:buffer';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { URL } from 'node:url';

import { _electron as electron } from 'playwright';

import { createWindowsInnoTestInstallation } from './windows-native-test-install.mjs';

if (process.platform !== 'win32') {
  throw new Error('The installed Desktop journey currently targets the Windows release.');
}

function resolveDesktopJourneyPlatformOrigin(raw = process.env.WORKDUDE_DESKTOP_JOURNEY_PLATFORM_ORIGIN) {
  const value = raw?.trim() || 'http://127.0.0.1:4000';
  let url;
  try {
    url = new URL(value);
  } catch (cause) {
    throw new Error('WORKDUDE_DESKTOP_JOURNEY_PLATFORM_ORIGIN must be a valid loopback HTTP origin.', {
      cause,
    });
  }
  const port = Number(url.port);
  if (
    url.protocol !== 'http:' ||
    url.hostname !== '127.0.0.1' ||
    !url.port ||
    !Number.isSafeInteger(port) ||
    port < 1 ||
    port > 65_535 ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error(
      'WORKDUDE_DESKTOP_JOURNEY_PLATFORM_ORIGIN must be a loopback HTTP origin with an explicit port.',
    );
  }
  return url.origin;
}

const desktopPackage = JSON.parse(await readFile('apps/desktop/package.json', 'utf8'));
const desktopJourneyPlatformOrigin = resolveDesktopJourneyPlatformOrigin();
const installer = resolve(
  'apps/desktop/out/make',
  `inno/QoderWake-${desktopPackage.version}-Windows-x64-Setup.exe`,
);
const pageErrors = [];
const consoleErrors = [];
let installation;
let application;

const visibleHeading = async (page, name) => {
  await page.getByRole('heading', { name, exact: true }).first().waitFor({ state: 'visible' });
};

try {
  installation = await createWindowsInnoTestInstallation({
    installer,
    version: desktopPackage.version,
    prefix: 'workdude-desktop-journeys',
    expectedInstallerSha256: process.env.WORKDUDE_WINDOWS_CURRENT_SETUP_SHA256,
  });
  application = await electron.launch({
    executablePath: installation.applicationExecutable,
    args: [`--user-data-dir=${installation.userData}`],
    env: {
      ...installation.environment,
      WORKDUDE_AUTOMATION_WINDOW: 'hidden',
      WORKDUDE_PLATFORM_ORIGIN: desktopJourneyPlatformOrigin,
      WORKDUDE_PLATFORM_ACCESS_TOKEN: 'desktop-journey-token-at-least-32-characters',
      WORKDUDE_AI_GATEWAY_MODEL: 'gateway-model',
    },
    timeout: 60_000,
  });
  const page = await application.firstWindow({ timeout: 60_000 });
  page.setDefaultTimeout(30_000);
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('console', (message) => {
    if (message.type() !== 'error') return;
    const value = message.text();
    if (/Autofill|DevTools failed to load SourceMap/iu.test(value)) return;
    consoleErrors.push(value);
  });

  await visibleHeading(page, '我的Wakers');
  const operatorJourneyStarted = Date.now();
  const createWaker = async (name) => {
    await page.getByRole('button', { name: /新建\s*Waker/u }).click();
    const dialog = page.getByRole('dialog', { name: '新建 Waker' });
    await dialog.waitFor({ state: 'visible' });
    await dialog.getByRole('textbox', { name: '请输入 Waker 名称' }).fill(name);
    await dialog.getByRole('button', { name: '保存并启用' }).click();
    await dialog.waitFor({ state: 'hidden' });
    const success = page.locator('.cw-success-overlay');
    await success.waitFor({ state: 'visible' });
    await success.getByText(name, { exact: true }).waitFor({ state: 'visible' });
    await success.locator('.cw-success-close-btn').click();
    await success.waitFor({ state: 'hidden' });
    await page.getByRole('heading', { name, exact: true }).waitFor({ state: 'visible' });
  };
  await createWaker('桌面验收规划');
  await createWaker('桌面验收执行');

  await page.getByRole('tab', { name: '我的群组', exact: true }).click();
  await page.getByRole('button', { name: /新建群组/u }).click();
  const groupDialog = page.getByRole('dialog', { name: '创建群组' });
  await groupDialog.waitFor({ state: 'visible' });
  await groupDialog.getByRole('checkbox', { name: '桌面验收规划' }).check();
  await groupDialog.getByRole('checkbox', { name: '桌面验收执行' }).check();
  await groupDialog.getByRole('textbox', { name: '群聊标题', exact: true }).fill('桌面验收群组');
  const currentLeader = groupDialog.getByRole('button', { name: '桌面验收规划 是当前 Leader' });
  if (!(await currentLeader.isDisabled())) {
    throw new Error('The first selected Waker must remain the default group Leader.');
  }
  await groupDialog.getByRole('button', { name: /创建/u }).click();
  await groupDialog.waitFor({ state: 'hidden' });
  await page.getByRole('heading', { name: '桌面验收群组', exact: true }).waitFor({ state: 'visible' });
  const operatorJourneyMilliseconds = Date.now() - operatorJourneyStarted;
  if (operatorJourneyMilliseconds > 300_000) {
    throw new Error(`Waker/group acceptance exceeded five minutes: ${operatorJourneyMilliseconds}ms`);
  }

  await page.getByRole('link', { name: 'Waker 管理', exact: true }).click();
  await page.getByRole('tab', { name: '我的Waker', exact: true }).click();
  await page.getByRole('link', { name: /查看 桌面验收规划 的角色详情/u }).click();
  await page.getByText('记忆与积累', { exact: true }).waitFor({ state: 'visible' });

  const wakerRoutes = [
    ['项目', '项目'],
    ['自动任务', '自动任务'],
    ['对话任务', '对话任务'],
    ['工作流', 'WakerFlow 管理'],
    ['记忆', '记忆'],
    ['技能', 'Skill'],
    ['连接器', '连接器'],
    ['权限', '权限'],
  ];
  const wakerNavigation = page.getByLabel('Waker 详情导航');
  for (const [navigation, heading] of wakerRoutes) {
    await wakerNavigation.getByRole('link', { name: navigation, exact: true }).click();
    await visibleHeading(page, heading);
    if (navigation === '项目') {
      await page.getByRole('button', { name: '新建', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: '新建项目' });
      await dialog.getByLabel('项目名称 *').fill('桌面验收项目');
      await dialog.getByLabel('来源 1 类型').selectOption('git_repository');
      await dialog
        .getByLabel('https://github.com/org/repo.git')
        .fill('https://github.com/octocat/Hello-World.git');
      await dialog.getByLabel('main').fill('main');
      await dialog.getByRole('button', { name: '保存', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      await page.getByText('桌面验收项目', { exact: true }).waitFor({ state: 'visible' });
    }
    if (navigation === '自动任务') {
      await page.getByRole('button', { name: /新建/u }).first().click();
      const dialog = page.getByRole('dialog', { name: '新建自动任务' });
      await dialog.getByLabel('名称').fill('桌面验收巡检');
      await dialog.getByRole('button', { name: '项目', exact: true }).click();
      await dialog.getByLabel('自动任务描述').fill('检查桌面安装、配置、持久化与证据。');
      if (!(await dialog.getByRole('button', { name: '保存', exact: true }).isDisabled())) {
        throw new Error('Automation Save must remain disabled without an authorized workspace reference.');
      }
      await dialog.getByRole('button', { name: '取消', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
    }
    if (navigation === '工作流') {
      await page.getByRole('button', { name: '新建 WakerFlow' }).click();
      await page.getByRole('heading', { name: '未命名 WakerFlow', exact: true }).waitFor({
        state: 'visible',
      });
      if (!(await page.getByRole('button', { name: '运行', exact: true }).isDisabled())) {
        throw new Error('A blank WakerFlow must not run before a valid graph is published.');
      }
    }
    if (navigation === '记忆') {
      await page.getByRole('button', { name: '版本管理' }).click();
      const dialog = page.getByRole('dialog', { name: '版本管理' });
      await dialog.waitFor({ state: 'visible' });
      await dialog.getByLabel('关闭').click();
    }
    if (navigation === '技能') {
      await page.getByRole('button', { name: '上传 Skill' }).click();
      const dialog = page.getByRole('dialog', { name: '上传 Skill' });
      await dialog.locator('input[type=file]').setInputFiles({
        name: 'desktop-acceptance.md',
        mimeType: 'text/markdown',
        buffer: Buffer.from(
          '---\nname: desktop-acceptance\ndescription: Verify the installed Desktop\n---\n# Verify',
        ),
      });
      await dialog.getByRole('button', { name: '添加 Skill' }).click();
      await dialog.waitFor({ state: 'hidden' });
      await page.getByRole('tab', { name: '我的技能' }).click();
      await page.getByText('desktop-acceptance', { exact: true }).waitFor({ state: 'visible' });
    }
    if (navigation === '连接器') {
      await page.getByRole('tab', { name: '已安装' }).click();
      await page.getByRole('button', { name: '添加', exact: true }).click();
      await page.getByRole('menuitem', { name: '手动填写配置', exact: true }).click();
      const dialog = page.getByRole('dialog').filter({
        has: page.getByRole('heading', { name: '添加 MCP 服务器', exact: true }),
      });
      await dialog.getByPlaceholder('my-mcp-server').fill('桌面验收 MCP');
      await dialog
        .getByPlaceholder('npx -y @modelcontextprotocol/server-filesystem')
        .fill('npx -y @workdude/acceptance-mcp');
      await dialog.getByRole('button', { name: '添加', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      await page.getByText('桌面验收 MCP', { exact: true }).waitFor({ state: 'visible' });
    }
    if (navigation === '权限') {
      await page.getByRole('tab', { name: '内置工具' }).click();
      const bashRow = page.getByRole('row').filter({ hasText: /^Bash/u });
      await bashRow.getByRole('radio', { name: '允许' }).waitFor({ state: 'visible' });
      await bashRow.getByRole('radio', { name: '询问' }).waitFor({ state: 'visible' });
      await bashRow.getByRole('radio', { name: '禁用' }).waitFor({ state: 'visible' });
    }
  }

  const globalRoutes = [
    ['Chat', '你好，今天我能帮你什么？'],
    ['WakerFlow', 'WakerFlow'],
    ['任务看板', '任务看板'],
    ['知识库', '知识库管理'],
    ['IM', '@Waker'],
  ];
  const mainNavigation = page.getByRole('navigation', { name: '产品导航' });
  for (const [navigation, heading] of globalRoutes) {
    await mainNavigation.getByRole('link', { name: navigation, exact: true }).click();
    if (navigation === 'Chat') {
      await page.getByRole('button', { name: 'Open chat 桌面验收规划' }).click();
      await page.getByRole('button', { name: '查看 Waker 详情' }).waitFor({ state: 'visible' });
    } else {
      await visibleHeading(page, heading);
    }
    if (navigation === '任务看板') {
      await page.getByRole('combobox', { name: '类型' }).waitFor({ state: 'visible' });
      await page.getByRole('tab', { name: '泳道' }).click();
      await page.getByLabel('泳道').waitFor({ state: 'visible' });
      await page.getByRole('tab', { name: '列表' }).click();
    }
    if (navigation === '知识库') {
      await page.getByRole('button', { name: /新建知识库/u }).click();
      const dialog = page.getByRole('dialog', { name: '新建知识库' });
      await dialog.getByLabel(/标题/u).fill('桌面验收知识库');
      await dialog.getByRole('button', { name: '确定', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      await page.locator('[data-knowledge-detail]').waitFor({ state: 'visible' });
      await page.getByRole('button', { name: '返回', exact: true }).click();
      await page.getByRole('button', { name: '打开 桌面验收知识库' }).waitFor({ state: 'visible' });
    }
    if (navigation === 'IM') {
      await page.getByRole('tab', { name: 'IM 连接', exact: true }).click();
      const qqCard = page.getByText('QQ 机器人', { exact: true }).locator('..').locator('..').locator('..');
      await qqCard.getByRole('button', { name: '添加机器人', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: '配置 QQ 机器人 QQ 机器人文档' });
      await dialog.getByPlaceholder('请输入 QQ 机器人 App ID').fill('desktop-acceptance-app');
      await dialog.getByPlaceholder('请输入 QQ 机器人 App Secret').fill('desktop-acceptance-secret');
      await dialog.getByRole('button', { name: '保存', exact: true }).click();
      await dialog.waitFor({ state: 'hidden' });
      await page.getByText('已配置 1 个', { exact: true }).waitFor({ state: 'visible' });
    }
  }

  await mainNavigation.getByRole('link', { name: 'Waker 管理', exact: true }).click();
  await visibleHeading(page, '我的Wakers');
  await page.getByRole('link', { name: /查看 桌面验收规划 的角色详情/u }).click();
  const reboundNavigation = page.getByLabel('Waker 详情导航');
  await reboundNavigation.getByRole('link', { name: '知识库', exact: true }).click();
  await visibleHeading(page, '知识库');
  await page.getByRole('button', { name: '绑定知识库' }).click();
  const bindDialog = page.getByRole('dialog', { name: '绑定知识库' });
  const knowledgeCheckbox = bindDialog.getByRole('checkbox', { name: /桌面验收知识库/u });
  try {
    await knowledgeCheckbox.waitFor({ state: 'visible' });
  } catch (cause) {
    const dialogText = await bindDialog.innerText().catch(() => '<dialog unavailable>');
    const checkboxLabels = await bindDialog
      .getByRole('checkbox')
      .evaluateAll((checkboxes) =>
        checkboxes.map(
          (checkbox) => checkbox.closest('label')?.innerText.trim() ?? checkbox.getAttribute('aria-label'),
        ),
      )
      .catch(() => []);
    throw new Error(
      `Created knowledge base is missing from the bind dialog. dialog=${JSON.stringify(dialogText)} checkboxes=${JSON.stringify(checkboxLabels)} page=${JSON.stringify(pageErrors)} console=${JSON.stringify(consoleErrors)}`,
      { cause },
    );
  }
  await knowledgeCheckbox.check();
  await bindDialog.getByRole('button', { name: '确认', exact: true }).click();
  await bindDialog.waitFor({ state: 'hidden' });
  await page.getByText('已连接', { exact: true }).waitFor({ state: 'visible' });

  await mainNavigation.getByRole('link', { name: 'Waker 管理', exact: true }).click();
  await visibleHeading(page, '我的Wakers');
  await page.getByRole('link', { name: /查看 桌面验收规划 的角色详情/u }).click();
  await page.getByLabel('Waker 详情导航').getByRole('link', { name: 'IM', exact: true }).click();
  await visibleHeading(page, 'IM 渠道');
  await page.getByRole('button', { name: '管理IM渠道' }).waitFor({ state: 'visible' });

  if (pageErrors.length || consoleErrors.length) {
    throw new Error(
      `Installed Desktop emitted UI errors:\npage=${JSON.stringify(pageErrors)}\nconsole=${JSON.stringify(consoleErrors)}`,
    );
  }
  process.stdout.write(
    `Installed Windows Desktop primary journeys verified for ${wakerRoutes.length + globalRoutes.length + 3} product states; two-Waker group=${operatorJourneyMilliseconds}ms.\n`,
  );
} finally {
  await application?.close().catch(() => undefined);
  if (installation) {
    await installation.uninstallAndAssertApplicationRemoval();
    await installation.cleanup();
  }
}
