/**
 * 调试：打开检索页，抓控制台与网络失败，并直接在页面里跑一次 fetch 计时。
 * 用法（在 apps/web 下）：node scripts/debug-search.mjs
 */
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
  page.on("console", (m) => logs.push(`[${m.type()}] ${m.text()}`));
  page.on("pageerror", (e) => logs.push(`[pageerror] ${e}`));
  page.on("requestfailed", (r) => logs.push(`[failed] ${r.url()} ${r.failure()?.errorText}`));

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle2", timeout: 60000 });
  await wait(2500);

  const buttons = await page.$$("aside button");
  for (const b of buttons) {
    const text = await page.evaluate((el) => el.textContent || "", b);
    if (text.includes("检索发现")) {
      await b.click();
      break;
    }
  }
  await wait(3000);

  const direct = await page.evaluate(async () => {
    const t0 = performance.now();
    const res = await fetch("/api/arxiv/search?q=all%3Aretrieval%20augmented%20generation&max_results=5");
    const text = await res.text();
    return { status: res.status, ms: Math.round(performance.now() - t0), len: text.length, head: text.slice(0, 120) };
  });

  console.log("direct fetch:", JSON.stringify(direct));
  console.log("logs:", JSON.stringify(logs.slice(0, 8), null, 2));
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
