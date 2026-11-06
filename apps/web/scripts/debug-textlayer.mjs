/** 调试文本层：打印 .textLayer 的结构与控制台错误。 */
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu", "--window-size=1600,1000"],
});
try {
  const page = await browser.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(`[${m.type()}] ${m.text().slice(0, 160)}`));
  page.on("pageerror", (e) => logs.push(`[pageerror] ${String(e).slice(0, 160)}`));
  await page.setViewport({ width: 1600, height: 1000 });
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle2", timeout: 60000 });
  await wait(5000);

  const info = await page.evaluate(() => {
    const layer = document.querySelector(".textLayer");
    if (!layer) return { exists: false };
    return {
      exists: true,
      html: layer.innerHTML.length,
      children: layer.children.length,
      tags: Array.from(layer.children).slice(0, 5).map((c) => c.tagName),
      style: layer.getAttribute("style"),
      firstText: (layer.textContent || "").slice(0, 80),
    };
  });
  console.log(JSON.stringify(info, null, 2));
  console.log("logs:", JSON.stringify(logs.slice(0, 10), null, 2));
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
