"use client";

import { useEffect, useRef, useState } from "react";

import type { GraphPayload } from "@/lib/api";
import { getGraph, getSurvey } from "@/lib/api";

const ROLE_STYLE: Record<string, { bg: string; border: string; size: number; label: string }> = {
  foundational: { bg: "#A63C2A", border: "#7d2a1d", size: 34, label: "基石" },
  bridge: { bg: "#1F4E63", border: "#143441", size: 28, label: "桥梁" },
  derivative: { bg: "#8B8779", border: "#6d6a5e", size: 22, label: "衍生" },
  normal: { bg: "#CFCABD", border: "#a8a294", size: 16, label: "普通" },
};

export default function CitationGraphView({ onOpenDoc }: { onOpenDoc: (docId: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [payload, setPayload] = useState<GraphPayload | null>(null);
  const [survey, setSurvey] = useState<{ summary: string; future_work: { title: string; text: string; page: number }[] } | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getGraph(), getSurvey()])
      .then(([graph, text]) => {
        if (!alive) return;
        setPayload(graph);
        setSurvey(text);
      })
      .catch((e: Error) => alive && setError(e.message.slice(0, 160)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!payload || !containerRef.current) return;
    let disposed = false;
    let cy: import("cytoscape").Core | null = null;

    (async () => {
      const cytoscape = (await import("cytoscape")).default;
      if (disposed || !containerRef.current) return;

      const elements = [
        ...payload.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.label.length > 26 ? `${n.label.slice(0, 26)}…` : n.label,
            role: n.role,
            library: n.in_library,
            pagerank: n.pagerank,
          },
        })),
        ...payload.edges.map((e, i) => ({
          data: { id: `e${i}`, source: e.source, target: e.target, kind: e.kind },
        })),
      ];

      cy = cytoscape({
        container: containerRef.current,
        elements,
        wheelSensitivity: 0.2,
        style: [
          {
            selector: "node",
            style: {
              "background-color": (ele: import("cytoscape").NodeSingular) =>
                ROLE_STYLE[ele.data("role") as string]?.bg ?? "#CFCABD",
              "border-color": (ele: import("cytoscape").NodeSingular) =>
                ROLE_STYLE[ele.data("role") as string]?.border ?? "#a8a294",
              "border-width": 1,
              width: (ele: import("cytoscape").NodeSingular) =>
                ele.data("library") ? ROLE_STYLE[ele.data("role") as string]?.size ?? 18 : 11,
              height: (ele: import("cytoscape").NodeSingular) =>
                ele.data("library") ? ROLE_STYLE[ele.data("role") as string]?.size ?? 18 : 11,
              label: "data(label)",
              "font-size": 8,
              "font-family": "Consolas, monospace",
              color: "#191813",
              "text-valign": "bottom",
              "text-margin-y": 4,
              // 只给库内节点和有角色的外部节点加标签，否则 60 个标签会糊成一团
              "text-opacity": (ele: import("cytoscape").NodeSingular) =>
                ele.data("library") || ele.data("role") !== "normal" ? 1 : 0,
              "text-max-width": 90,
              "text-wrap": "ellipsis",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1,
              "line-color": (ele: import("cytoscape").EdgeSingular) =>
                ele.data("kind") === "internal" ? "#A63C2A" : "#C9C3B4",
              "target-arrow-color": (ele: import("cytoscape").EdgeSingular) =>
                ele.data("kind") === "internal" ? "#A63C2A" : "#C9C3B4",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.6,
              "curve-style": "bezier",
              opacity: (ele: import("cytoscape").EdgeSingular) =>
                ele.data("kind") === "internal" ? 0.9 : 0.35,
            },
          },
          { selector: "node:selected", style: { "border-width": 3, "border-color": "#191813" } },
        ],
        layout: {
          name: "cose",
          animate: false,
          padding: 40,
          nodeRepulsion: () => 9000,
          idealEdgeLength: () => 90,
        },
      });

      cy.on("tap", "node", (evt) => {
        const id = evt.target.id() as string;
        setSelected(id);
        if (payload.nodes.find((n) => n.id === id)?.in_library) onOpenDoc(id);
      });
    })();

    return () => {
      disposed = true;
      cy?.destroy();
    };
  }, [payload, onOpenDoc]);

  return (
    <div className="flex h-screen min-w-0 flex-1 flex-col">
      <header className="sheet-grid border-b border-haze bg-mist px-10 pb-4 pt-7">
        <h1 className="font-serif text-[26px] tracking-tight">局域引用图谱</h1>
        <p className="mt-1.5 text-[12px] text-ink/55">
          节点大小按库内/库外区分，颜色为图论角色；红色边是库内互引。
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-[10.5px] text-ink/50">
          {payload ? (
            <>
              <span>{payload.stats.documents} 篇</span>
              <span>{payload.stats.nodes} 节点</span>
              <span>{payload.stats.edges} 边</span>
              <span>{payload.stats.internal_edges} 条库内互引</span>
              <span>密度 {payload.stats.density}</span>
            </>
          ) : (
            <span>加载中…</span>
          )}
          <span className="ml-auto flex gap-4">
            {Object.entries(ROLE_STYLE).map(([role, style]) => (
              <span key={role} className="flex items-center gap-1">
                <i className="inline-block h-2 w-2 rounded-full" style={{ background: style.bg }} />
                {style.label}
              </span>
            ))}
          </span>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div ref={containerRef} className="min-h-0 flex-1 bg-paper" />
        <aside className="w-[380px] shrink-0 overflow-y-auto border-l border-haze bg-mist px-5 py-4">
          {error ? <p className="text-[12px] text-signal">{error}</p> : null}
          {survey ? (
            <>
              <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">自动综述</p>
              <p className="mt-2 whitespace-pre-wrap text-[12.5px] leading-[1.85] text-ink/80">
                {survey.summary}
              </p>
              {survey.future_work.length > 0 ? (
                <div className="mt-5">
                  <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink/40">
                    待探索方向
                  </p>
                  <ul className="mt-2 space-y-3">
                    {survey.future_work.map((item, i) => (
                      <li key={i} className="border-l-2 border-blueprint/40 pl-2">
                        <p className="font-mono text-[10px] text-ink/40">
                          p.{item.page + 1} · {item.title.slice(0, 24)}
                        </p>
                        <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/70">
                          {item.text.slice(0, 160)}…
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-[12px] text-ink/50">正在生成综述…</p>
          )}
          {selected ? (
            <p className="mt-4 font-mono text-[10px] text-ink/35">已选中 {selected}</p>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
