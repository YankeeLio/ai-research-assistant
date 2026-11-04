export type Evidence = {
  chunk_id: string;
  page: number;
  section: string;
  text: string;
  score: number;
  block_ids: string[];
};

export type QaEvent =
  | { type: "status"; message: string }
  | { type: "evidence"; items: Evidence[] }
  | { type: "delta"; text: string }
  | { type: "done"; warnings: string[]; mode: string }
  | { type: "error"; message: string };

/**
 * 流式问答：直接消费 SSE 帧。
 * 用 fetch + ReadableStream 而不是 EventSource，因为 EventSource 无法带自定义请求头，
 * 也无法在 POST 体里传参数（后续接入多轮会话时需要）。
 */
export async function askStream(
  docId: string,
  question: string,
  onEvent: (e: QaEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(
    `/api/qa/stream?doc_id=${encodeURIComponent(docId)}&q=${encodeURIComponent(question)}`,
    { signal },
  );
  if (!res.ok || !res.body) {
    onEvent({ type: "error", message: `HTTP ${res.status}` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx = buffer.indexOf("\n\n");
    while (idx >= 0) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (line) {
        try {
          onEvent(JSON.parse(line.slice(6)) as QaEvent);
        } catch {
          // 单帧解析失败不应中断整个流
        }
      }
      idx = buffer.indexOf("\n\n");
    }
  }
}
