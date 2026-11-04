/**
 * UI 截图脚本：用本机 Edge 无头模式打开文献台，验证渲染并产出素材。
 *
 * 用法（在 apps/web 下）：
 *   node scripts/shot.mjs [输出目录]
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const URL = process.env.SHOT_URL || "http://127.0.0.1:3000/";
const outDir = path.resolve(process.argv[2] || "../../assets/shots");

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--window-size=1600,1000"],
});

const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 });

const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
page.on("pageerror", (err) => errors.push(String(err)));

await mkdir(outDir, { recursive: true });
await page.goto(URL, { waitUntil: "networkidle2", timeout: 60000 });
await wait(2500);
await page.screenshot({ path: path.join(outDir, "reader.png") });

const hasCanvas = Boolean(await page.$("canvas"));

// 翻到含引用锚点的页面
await page.keyboard.press("ArrowRight");
await wait(1200);
await page.keyboard.press("ArrowRight");
await wait(1500);
await page.screenshot({ path: path.join(outDir, "reader-anchors.png") });

// 章节树
const tabs = await page.$$("button.tab");
if (tabs[2]) {
  await tabs[2].click();
  await wait(600);
  await page.screenshot({ path: path.join(outDir, "sections.png") });
}
// 参考文献
if (tabs[3]) {
  await tabs[3].click();
  await wait(600);
  await page.screenshot({ path: path.join(outDir, "references.png") });
}

console.log(JSON.stringify({ canvas: hasCanvas, errors: errors.slice(0, 5) }, null, 2));
await browser.close();
