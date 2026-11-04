/**
 * 技术文档 HTML → PDF（A4，带页眉页脚与页码）
 * 用法（在仓库根目录）：node apps/web/scripts/build-report-pdf.mjs
 */
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..", "..");
const htmlPath = path.join(root, "docs", "report", "report.html");
const outPath = path.join(root, "docs", "SciLoom-技术文档.pdf");

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: "new",
  args: ["--no-sandbox", "--allow-file-access-from-files", "--font-render-hinting=none"],
});

try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle0", timeout: 120000 });
  // 等图片解码完，避免出现空白占位
  await page.evaluate(async () => {
    await Promise.all(
      Array.from(document.images)
        .filter((img) => !img.complete)
        .map(
          (img) =>
            new Promise((res) => {
              img.onload = res;
              img.onerror = res;
            }),
        ),
    );
  });

  await page.pdf({
    path: outPath,
    format: "A4",
    printBackground: true,
    displayHeaderFooter: true,
    margin: { top: "18mm", bottom: "16mm", left: "16mm", right: "16mm" },
    headerTemplate: `<div style="width:100%;font-size:7pt;color:#8b8779;font-family:Consolas,monospace;padding:0 16mm;display:flex;justify-content:space-between;">
      <span>SciLoom 智研织机 · 技术文档</span><span>全国高校 AI 大模型挑战赛 · B 组</span></div>`,
    footerTemplate: `<div style="width:100%;font-size:7pt;color:#8b8779;font-family:Consolas,monospace;padding:0 16mm;text-align:center;">
      第 <span class="pageNumber"></span> 页 / 共 <span class="totalPages"></span> 页</div>`,
  });
  console.log("PDF 已生成:", outPath);
} finally {
  await browser.close().catch(() => {});
  process.exit(0);
}
