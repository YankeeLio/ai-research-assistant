/**
 * 问答面板截图：点第一个推荐问题，等待流式回答结束，截屏。
 * 用法（在 apps/web 下）：node scripts/shot-qa.mjs
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

// 本机 PATH 缺 System32，puppeteer 关闭浏览器时调 taskkill 会失败
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
  await wait(2500);

  const buttons = await page.$$("aside button");
  for (const b of buttons) {
    const text = await page.evaluate((el) => el.textContent || "", b);
    if (text.includes("GPU")) {
      await b.click();
      break;
    }
  }

  await wait(30000);
  await mkdir(outDir, { recursive: true });
  await page.screenshot({ path: path.join(outDir, "qa.png") });
  console.log("saved qa.png");
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
