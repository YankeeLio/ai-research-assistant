/**
 * 把片头/片尾卡渲染成 1920×1080 PNG，供视频剪辑直接使用。
 * 用法（在 apps/web 下）：node scripts/render-cards.mjs
 */
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..", "..");

const cards = [
  ["title-card.html", "title-card.png"],
  ["end-card.html", "end-card.png"],
];

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--allow-file-access-from-files", "--font-render-hinting=none"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  for (const [src, out] of cards) {
    const file = pathToFileURL(path.join(root, "assets", "video", src)).href;
    await page.goto(file, { waitUntil: "networkidle0" });
    await page.screenshot({ path: path.join(root, "assets", "video", out) });
    console.log("saved", out);
  }
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
