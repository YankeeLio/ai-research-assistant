/**
 * 中英对照截图：切到"对照"页签，截一张；再滚动左栏，验证右栏联动。
 * 用法（在 apps/web 下）：node scripts/shot-bilingual.mjs
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
  await wait(2500);

  const tabs = await page.$$("button.tab");
  await tabs[1].click();
  await wait(3500);
  await mkdir(outDir, { recursive: true });
  await page.screenshot({ path: path.join(outDir, "bilingual.png") });

  // 滚动左栏，检查右栏是否被带到同一段
  await page.evaluate(() => {
    const pane = document.querySelectorAll(".grid > div")[0];
    if (pane) pane.scrollTop = 1400;
    pane?.dispatchEvent(new Event("scroll"));
  });
  await wait(1200);
  await page.screenshot({ path: path.join(outDir, "bilingual-scrolled.png") });

  const offsets = await page.evaluate(() => {
    const panes = document.querySelectorAll(".grid > div");
    return Array.from(panes).map((p) => p.scrollTop);
  });
  console.log(JSON.stringify({ scrollTop: offsets }));
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
