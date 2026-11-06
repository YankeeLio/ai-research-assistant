/**
 * 样板片段录制：用 CDP 截屏流录下真实操作，再用 ffmpeg 合成 1080p MP4。
 *
 * 目的：验证"脚本驱动录屏 → 编码"这条流水线可用。
 * 一旦可用，完整演示视频的视觉轨就可以自动生成，人工只需要配音。
 *
 * 用法（在 apps/web 下）：node scripts/record-sample.mjs
 */
import { spawn } from "node:child_process";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";

process.env.PATH = `C:\\Windows\\System32;${process.env.PATH ?? ""}`;

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..", "..", "..");
const frameDir = path.join(root, "assets", "video", "frames-sample");
const outFile = path.join(root, "assets", "video", "sample.mp4");
const ffmpeg = path.join(
  root,
  "apps", "api", ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries",
  "ffmpeg-win-x86_64-v9.0.2.exe",
);

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  await rm(frameDir, { recursive: true, force: true });
  await mkdir(frameDir, { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=1"],
    defaultViewport: { width: 1600, height: 1000 },
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1000 });
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle2", timeout: 60000 });
  await wait(4000);

  // 用 CDP 截屏流抓帧：每帧带时间戳，后面按真实节奏编码
  const client = await page.target().createCDPSession();
  const frames = [];
  await client.send("Page.startScreencast", {
    format: "jpeg",
    quality: 90,
    maxWidth: 1600,
    maxHeight: 1000,
    everyNthFrame: 1,
  });
  client.on("Page.screencastFrame", async (frame) => {
    frames.push({ data: frame.data, ts: frame.metadata.timestamp });
    try {
      await client.send("Page.screencastFrameAck", { sessionId: frame.sessionId });
    } catch {
      /* 页面切换时 ack 可能失败，忽略 */
    }
  });

  // —— 一段 12 秒的真实操作：切到章节树、展开、切到参考文献 ——
  const clickTab = async (label) => {
    const tabs = await page.$$("button.tab");
    for (const t of tabs) {
      const text = await page.evaluate((el) => el.textContent || "", t);
      if (text.includes(label)) {
        await t.click();
        return true;
      }
    }
    return false;
  };

  await wait(1200);
  await clickTab("章节树");
  await wait(2500);
  await clickTab("参考文献");
  await wait(2500);
  await clickTab("阅读");
  await wait(2500);
  await page.keyboard.press("ArrowRight");
  await wait(2000);

  await client.send("Page.stopScreencast");
  await browser.close();

  console.log(`抓到 ${frames.length} 帧`);
  if (frames.length < 10) throw new Error("帧数太少，录制失败");

  // 写入 jpg + 每帧时长
  const lines = [];
  for (let i = 0; i < frames.length; i += 1) {
    const file = path.join(frameDir, `f${String(i).padStart(5, "0")}.jpg`);
    await writeFile(file, Buffer.from(frames[i].data, "base64"));
    const next = frames[i + 1]?.ts ?? frames[i].ts + 0.1;
    // 截屏流只在画面变化时出帧，静止画面要"持有"到下一帧——上限给到 5 秒
    const dur = Math.max(0.02, Math.min(5.0, next - frames[i].ts));
    lines.push(`file '${file.replace(/\\/g, "/")}'`);
    lines.push(`duration ${dur.toFixed(3)}`);
  }
  // 末帧再显示一次，避免最后一帧被吞
  lines.push(`file '${path.join(frameDir, `f${String(frames.length - 1).padStart(5, "0")}.jpg`).replace(/\\/g, "/")}'`);
  const listFile = path.join(frameDir, "list.txt");
  await writeFile(listFile, lines.join("\n"), "utf8");

  await new Promise((resolve, reject) => {
    const proc = spawn(ffmpeg, [
      "-y",
      "-f", "concat",
      "-safe", "0",
      "-i", listFile,
      "-vf", "scale=1920:1200:flags=lanczos,pad=1920:1200:(ow-iw)/2:(oh-ih)/2,crop=1920:1080:0:60",
      "-r", "30",
      "-c:v", "libx264",
      "-preset", "medium",
      "-crf", "20",
      "-pix_fmt", "yuv420p",
      outFile,
    ], { stdio: "inherit" });
    proc.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg 退出码 ${code}`))));
  });

  console.log("已生成:", outFile);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
