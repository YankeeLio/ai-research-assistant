/**
 * 自动生成演示视频的"画面轨"（无声，供后续配音）。
 *
 * 场景顺序对应 docs/VIDEO_SCRIPT.md 的 10 个分镜，动作全部走真实界面。
 * 每个场景独立 try/catch：某个场景失败（比如 arXiv 限流）不会中断整段录制。
 *
 * 用法（在 apps/web 下）：
 *   node scripts/record-demo.mjs            # 录制并编码
 *   node scripts/record-demo.mjs --no-encode # 只抓帧，不编码（调试用）
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
const frameDir = path.join(root, "assets", "video", "frames-demo");
const outFile = path.join(root, "assets", "video", "demo-silent.mp4");
const ffmpeg = path.join(
  root, "apps", "api", ".venv", "Lib", "site-packages", "imageio_ffmpeg", "binaries",
  "ffmpeg-win-x86_64-v9.0.2.exe",
);
const NO_ENCODE = process.argv.includes("--no-encode");

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

  // 录制前清掉上一轮留下的 v1，保证"去重"场景演示的是同一工作的不同版本（same_work），
  // 而不是同一文件的重复上传（identical）
  try {
    const list = await (await fetch("http://127.0.0.1:8000/api/documents")).json();
    for (const doc of list) {
      if (String(doc.file_name).endsWith("1706.03762v1.pdf")) {
        await fetch(`http://127.0.0.1:8000/api/documents/${doc.doc_id}`, { method: "DELETE" });
        console.log("  预先删除旧的 v1:", doc.doc_id);
      }
    }
  } catch (err) {
    console.log("  清理旧 v1 失败（不影响录制）:", String(err).slice(0, 60));
  }

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle2", timeout: 90000 });
  await wait(5000);

  const client = await page.target().createCDPSession();
  const frames = [];
  await client.send("Page.startScreencast", {
    format: "jpeg", quality: 88, maxWidth: 1600, maxHeight: 1000, everyNthFrame: 1,
  });
  client.on("Page.screencastFrame", async (f) => {
    // 用本地到达时间而不是 CDP 的 metadata.timestamp：
    // 后者与实际墙钟不成正比，直接拿它算时长会把 145 秒的正片压成 72 秒
    frames.push({ data: f.data, ts: Date.now() / 1000 });
    try { await client.send("Page.screencastFrameAck", { sessionId: f.sessionId }); } catch { /* ignore */ }
  });

  const clickByText = async (selector, text, exact = false) => {
    const els = await page.$$(selector);
    for (const el of els) {
      const t = await page.evaluate((n) => n.textContent || "", el);
      if (exact ? t.trim() === text : t.includes(text)) {
        await el.click();
        return true;
      }
    }
    return false;
  };
  // 每个场景有一个"目标时长"，动作做完后补足剩余时间，
  // 让画面节奏与 docs/VIDEO_SCRIPT.md 的旁白时长对齐，配音时不用来回拉时间轴
  const sceneTimings = [];
  let recordStart = 0;
  const scene = async (name, target, fn) => {
    if (!recordStart) recordStart = Date.now() / 1000;
    const t0 = Date.now();
    const startOffset = t0 / 1000 - recordStart;
    try {
      await fn();
    } catch (err) {
      console.log(`  ${name} 失败: ${String(err).slice(0, 80)}`);
      await wait(1500);
    }
    const spent = (Date.now() - t0) / 1000;
    if (spent < target) await wait((target - spent) * 1000);
    const endOffset = Date.now() / 1000 - recordStart;
    sceneTimings.push({ name, start: startOffset, end: endOffset });
    console.log(
      `  ${name} 完成 ${spent.toFixed(1)}s → 补足到 ${target}s（${startOffset.toFixed(1)}–${endOffset.toFixed(1)}s）`,
    );
  };

  // 镜 1：文献台全景
  await scene("镜1 文献台", 45, async () => {
    await wait(2500);
    await page.evaluate(() => {
      const rail = document.querySelector("aside nav");
      if (rail) rail.scrollTop = 180;
    });
    await wait(2200);
    await page.evaluate(() => {
      const rail = document.querySelector("aside nav");
      if (rail) rail.scrollTop = 0;
    });
    await wait(1800);
  });

  // 镜 2：语义去重（上传 v1 触发预警）
  await scene("镜2 去重", 50, async () => {
    const input = await page.$('input[type="file"]');
    if (!input) throw new Error("找不到上传输入");
    await input.uploadFile(path.join(root, "pdf", "1706.03762v1.pdf"));
    // 解析 + 指纹比对需要几秒，等预警卡片出现
    for (let i = 0; i < 24; i += 1) {
      const has = await page.evaluate(() =>
        document.body.innerText.includes("疑似重复") || document.body.innerText.includes("已存在完全相同"),
      );
      if (has) break;
      await wait(1500);
    }
    await wait(5000);
    // 关掉预警卡，否则它会一直压在后几个场景的右下角
    await page.evaluate(() => {
      const card = [...document.querySelectorAll("div")].find((d) =>
        (d.textContent || "").startsWith("疑似重复") || (d.textContent || "").startsWith("库中已存在"),
      );
      const btn = card?.querySelector('button[aria-label="关闭"]');
      if (btn) btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await wait(800);
  });

  // 镜 3：章节树与表格
  await scene("镜3 解析结构", 40, async () => {
    await clickByText("button.tab", "章节树");
    await wait(2800);
    await page.evaluate(() => window.scrollTo(0, 0));
    await clickByText("button.tab", "表格");
    await wait(2600);
  });

  // 镜 4：抗幻觉问答
  await scene("镜4 问答", 60, async () => {
    await clickByText("aside button", "Attention Is All You Need");
    await wait(3500);
    await clickByText("button.tab", "阅读");
    await wait(1200);
    await clickByText("aside button", "GPU");
    for (let i = 0; i < 20; i += 1) {
      const done = await page.evaluate(() =>
        !document.body.innerText.includes("检索与生成中"),
      );
      if (done) break;
      await wait(1500);
    }
    await wait(3000);
  });

  // 镜 5：跨文献对比
  await scene("镜5 对比", 45, async () => {
    await clickByText("button.tab", "跨文献对比");
    await wait(2000);
    await clickByText("button", "对比这");
    for (let i = 0; i < 22; i += 1) {
      const done = await page.evaluate(() => document.body.innerText.includes("条证据"));
      if (done) break;
      await wait(2000);
    }
    await wait(4000);
  });

  // 镜 6：划词翻译
  await scene("镜6 划词", 30, async () => {
    await clickByText("button.tab", "阅读");
    await wait(2200);
    await page.evaluate(() => {
      const layer = document.querySelector(".textLayer");
      if (!layer) return;
      const spans = Array.from(layer.querySelectorAll("span"))
        .filter((s) => (s.textContent || "").trim().length > 90)
        .sort((a, b) => (b.textContent || "").length - (a.textContent || "").length);
      const target = spans[0];
      if (!target) return;
      const range = document.createRange();
      range.selectNodeContents(target);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
      layer.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
    await wait(5000);
  });

  // 镜 7：引用图谱
  await scene("镜7 图谱", 40, async () => {
    await clickByText("aside button", "引用图谱");
    await wait(6000);
    await page.mouse.move(800, 500);
    await wait(1500);
    await page.mouse.move(700, 620);
    await wait(3000);
  });

  // 镜 8：检索发现
  await scene("镜8 检索", 30, async () => {
    await clickByText("aside button", "检索发现");
    for (let i = 0; i < 20; i += 1) {
      const done = await page.evaluate(() => document.body.innerText.includes("检索结果 · "));
      if (done) break;
      await wait(2000);
    }
    await wait(5000);
  });

  // 镜 9：写作 Copilot
  await scene("镜9 写作", 35, async () => {
    await clickByText("aside button", "写作 Copilot");
    await wait(1800);
    await clickByText("button", "生成框架");
    for (let i = 0; i < 18; i += 1) {
      const done = await page.evaluate(() => document.body.innerText.includes("引用来源"));
      if (done) break;
      await wait(2000);
    }
    await wait(4500);
  });

  await client.send("Page.stopScreencast").catch(() => {});
  const recordEnd = Date.now() / 1000;
  await browser.close();
  console.log(`抓到 ${frames.length} 帧`);
  if (frames.length < 20) throw new Error("帧数太少，录制可能失败");

  const lines = [];
  for (let i = 0; i < frames.length; i += 1) {
    const file = path.join(frameDir, `f${String(i).padStart(5, "0")}.jpg`);
    await writeFile(file, Buffer.from(frames[i].data, "base64"));
    // 末帧要一直显示到录制结束，否则最后一段停留（约 20-30 秒）会整段丢失
    const next = frames[i + 1]?.ts ?? recordEnd;
    // 静止画面靠持有上一帧补齐，所以上限要覆盖整段停留（此前设 6 秒把 375 秒压成了 94 秒）
    const dur = Math.max(0.02, Math.min(60.0, next - frames[i].ts));
    lines.push(`file '${file.replace(/\\/g, "/")}'`);
    lines.push(`duration ${dur.toFixed(3)}`);
  }
  const lastFile = path.join(frameDir, `f${String(frames.length - 1).padStart(5, "0")}.jpg`);
  lines.push(`file '${lastFile.replace(/\\/g, "/")}'`);
  const listFile = path.join(frameDir, "list.txt");
  await writeFile(listFile, lines.join("\n"), "utf8");

  // 场景边界用录制墙钟记录，字幕按它切分才能和画面严格对齐。
  // offset 是"第一帧到达时刻 - 第一个场景开始时刻"：截屏流在页面加载阶段就开始出帧，
  // 这段画面会被编进正片，不补偿的话字幕会整体提前好几秒。
  const firstFrameTs = frames.length ? frames[0].ts : recordStart;
  const offset = Math.max(0, firstFrameTs - recordStart);
  await writeFile(
    path.join(frameDir, "timings.json"),
    JSON.stringify(
      {
        total: frames.length ? frames[frames.length - 1].ts - firstFrameTs : 0,
        offset,
        scenes: sceneTimings,
      },
      null,
      2,
    ),
    "utf8",
  );
  console.log(`场景边界已写入 timings.json（首帧偏移 ${offset.toFixed(1)}s）`);

  if (NO_ENCODE) {
    console.log("已抓帧，跳过编码");
    return;
  }

  await new Promise((resolve, reject) => {
    const proc = spawn(ffmpeg, [
      "-y", "-f", "concat", "-safe", "0", "-i", listFile,
      "-vf", "scale=1920:1200:flags=lanczos,crop=1920:1080:0:60",
      "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
      "-pix_fmt", "yuv420p", outFile,
    ], { stdio: "inherit" });
    proc.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg ${code}`))));
  });
  console.log("已生成:", outFile);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
