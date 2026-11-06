/**
 * 划词翻译验证：在 PDF 文本层选中一段，等译文气泡出现后截屏。
 * 用法（在 apps/web 下）：node scripts/shot-selection.mjs
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
  await wait(4000);

  // 翻到有正文的第 2 页
  await page.keyboard.press("ArrowRight");
  await wait(2500);

  const picked = await page.evaluate(() => {
    const layer = document.querySelector(".textLayer");
    if (!layer) return "no-text-layer";
    const spans = Array.from(layer.querySelectorAll("span"))
      .filter((s) => (s.textContent || "").trim().length > 60)
      .sort((a, b) => (b.textContent || "").length - (a.textContent || "").length);
    const target = spans[0];
    if (!target) return "no-span";
    const range = document.createRange();
    range.selectNodeContents(target);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    layer.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    return (target.textContent || "").slice(0, 80);
  });

  console.log("选中:", picked);
  await wait(6000);
  await mkdir(outDir, { recursive: true });
  await page.screenshot({ path: path.join(outDir, "selection.png") });
  console.log("saved selection.png");
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
