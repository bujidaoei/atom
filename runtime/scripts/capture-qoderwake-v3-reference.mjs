import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = resolve(root, process.argv[2] ?? 'test-results/v3-visual/qoderwake-playwright.png');
const origin = process.env.QODERWAKE_REFERENCE_ORIGIN ?? 'http://127.0.0.1:19820';
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1536, height: 769 }, deviceScaleFactor: 1 });
  await page.goto(`${origin}/management`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.getByRole('heading', { name: 'My Wakers', level: 1 }).waitFor();
  await page.locator('article').first().waitFor();
  await page.evaluate(async () => {
    await globalThis.document.fonts.ready;
    await Promise.all(
      [...globalThis.document.images].map((image) =>
        image.complete
          ? undefined
          : new Promise((resolveImage) => {
              image.addEventListener('load', () => resolveImage(), { once: true });
              image.addEventListener('error', () => resolveImage(), { once: true });
            }),
      ),
    );
  });
  await mkdir(dirname(output), { recursive: true });
  await page.screenshot({ path: output, animations: 'disabled' });
  process.stdout.write(`${output}\n`);
} finally {
  await browser.close();
}
