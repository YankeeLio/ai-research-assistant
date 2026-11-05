/**
 * 跨文献对比页截图：切到"跨文献对比"，点一次"对比"。
 * 用法（在 apps/web 下）：node scripts/shot-compare.mjs
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outDir = path.resolve("../../assets/shots");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--window-size=1600,1000"],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle2", timeout: 60000 });
  await wait(3000);

  // 切到"跨文献对比"页签
  const tabs = await page.$$("button.tab");
  for (const t of tabs) {
    const text = await page.evaluate((el) => el.textContent || "", t);
    if (text.includes("跨文献对比")) {
      await t.click();
      break;
    }
  }
  await wait(1500);

  // 点"对比这 N 篇"
  const buttons = await page.$$("button");
  for (const b of buttons) {
    const text = await page.evaluate((el) => el.textContent || "", b);
    if (text.startsWith("对比这")) {
      await b.click();
      break;
    }
  }

  await wait(45000);
  await mkdir(outDir, { recursive: true });
  await page.screenshot({ path: path.join(outDir, "compare.png") });
  console.log("saved compare.png");
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
