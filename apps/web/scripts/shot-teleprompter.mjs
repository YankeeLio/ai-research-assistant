/**
 * 渲染提词器预览图（只是给 README/文档看的截图，实际用浏览器打开 html 即可）。
 * 用法（在 apps/web 下）：node scripts/shot-teleprompter.mjs
 */
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..", "..");

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--allow-file-access-from-files", "--font-render-hinting=none"],
});
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  await page.goto(pathToFileURL(path.join(root, "assets", "video", "teleprompter.html")).href, {
    waitUntil: "networkidle0",
  });
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: path.join(root, "assets", "video", "teleprompter.png") });
  console.log("saved teleprompter.png");
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
