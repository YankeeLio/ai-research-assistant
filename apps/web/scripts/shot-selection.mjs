/**
 * 划词翻译验证：翻到有正文的页面，选中一段，等译文气泡出现后截屏。
 * 用法（在 apps/web 下）：node scripts/shot-selection.mjs
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outDir = path.resolve("../../assets/shots");
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const pickLongSpan = () => {
  const layer = document.querySelector(".textLayer");
  if (!layer) return { ok: false, reason: "no-layer" };
  const spans = Array.from(layer.querySelectorAll("span"))
    .filter((s) => (s.textContent || "").trim().length > 90)
    .sort((a, b) => (b.textContent || "").length - (a.textContent || "").length);
  const target = spans[0];
  if (!target) return { ok: false, reason: "no-long-span" };
  const range = document.createRange();
  range.selectNodeContents(target);
  const sel = window.getSelection();
  sel?.removeAllRanges();
  sel?.addRange(range);
  layer.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  return { ok: true, text: (target.textContent || "").slice(0, 70) };
};

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

  let picked = { ok: false, reason: "not-tried" };
  for (let i = 0; i < 8 && !picked.ok; i += 1) {
    picked = await page.evaluate(pickLongSpan);
    if (!picked.ok) {
      await page.keyboard.press("ArrowRight");
      await wait(1800);
    }
  }
  console.log("选中结果:", JSON.stringify(picked));

  await wait(5000);
  await mkdir(outDir, { recursive: true });
  await page.screenshot({ path: path.join(outDir, "selection.png") });
  console.log("saved selection.png");
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
