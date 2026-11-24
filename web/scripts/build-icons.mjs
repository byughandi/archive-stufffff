// Rasterises public/art/favicon.svg into the PNG icons the manifest and iOS need. Needs Playwright.
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const svg = readFileSync(new URL('../public/art/favicon.svg', import.meta.url), 'utf8');
const browser = await chromium.launch();
const jobs = [
  ['icon-192.png', 192, 0.84],
  ['icon-512.png', 512, 0.84],
  ['apple-touch-icon.png', 180, 0.8],
  ['icon-maskable-512.png', 512, 0.62] // safe zone for maskable icons
];
for (const [file, size, scale] of jobs) {
  const page = await browser.newPage({ viewport: { width: size, height: size } });
  const d = Math.round(size * scale);
  await page.setContent(
    `<body style="margin:0;background:#fff;display:grid;place-items:center;height:${size}px"><div style="width:${d}px;height:${d}px">${svg.replace('<svg ', '<svg width="100%" height="100%" ')}</div></body>`
  );
  await page.screenshot({ path: new URL(`../public/icons/${file}`, import.meta.url).pathname });
  await page.close();
}
await browser.close();
console.log('icons written');
