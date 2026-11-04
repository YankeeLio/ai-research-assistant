export type DocumentSummary = {
  doc_id: string;
  file_name: string;
  title: string;
  authors: string[];
  page_count: number;
  is_scanned: boolean;
  layout: string;
  uploaded_at: string;
  status: "parsing" | "ready" | "failed";
  error: string;
  content_fingerprint: string;
  version_hint: string;
  duplicate_of: string | null;
  duplicate_similarity: number;
  duplicate_verdict: string;
  duplicate_action: string;
  duplicate_message: string;
};

export type Block = {
  id: string;
  page: number;
  bbox: number[];
  text: string;
  kind: string;
  level: number;
  font_size: number;
  column: number;
};

export type Section = {
  id: string;
  title: string;
  level: number;
  page: number;
  block_id: string;
  children: Section[];
};

export type Reference = {
  index: number;
  text: string;
  page: number;
  block_id: string;
  year: number | null;
  arxiv_id: string | null;
  doi: string | null;
};

export type CiteAnchor = {
  ref_index: number;
  page: number;
  block_id: string;
  bbox: number[];
  raw: string;
};

export type TableModel = {
  id: string;
  page: number;
  bbox: number[];
  rows: string[][];
  caption: string;
};

export type ParsedDocument = {
  doc_id: string;
  file_name: string;
  title: string;
  authors: string[];
  abstract: string;
  layout: "single" | "double" | "mixed";
  is_scanned: boolean;
  sections: Section[];
  blocks: Block[];
  tables: TableModel[];
  references: Reference[];
  cite_anchors: CiteAnchor[];
  page_texts: string[];
  stats: {
    page_count: number;
    block_count: number;
    heading_count: number;
    table_count: number;
    figure_count: number;
    reference_count: number;
    cite_anchor_count: number;
    formula_block_count: number;
    char_count: number;
    scanned_pages: number;
    elapsed_ms: number;
  } | null;
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `请求失败 (${res.status})`);
  }
  return (await res.json()) as T;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  return json<DocumentSummary[]>(await fetch("/api/documents", { cache: "no-store" }));
}

export async function getParsed(docId: string): Promise<ParsedDocument> {
  return json<ParsedDocument>(await fetch(`/api/documents/${docId}/parsed`, { cache: "no-store" }));
}

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  return json<DocumentSummary>(await fetch("/api/documents/upload", { method: "POST", body: form }));
}

export async function deleteDocument(docId: string): Promise<void> {
  await fetch(`/api/documents/${docId}`, { method: "DELETE" });
}

export type VersionDiff = {
  old: { doc_id: string; label: string };
  new: { doc_id: string; label: string };
  similarity: number;
  summary: string;
  stats: Record<string, number[]>;
  sections: {
    title: string;
    status: string;
    similarity: number;
    added_sentences: number;
    removed_sentences: number;
  }[];
};

export async function resolveDuplicate(
  docId: string,
  action: "keep_existing" | "replace" | "keep_both",
): Promise<{ status: string }> {
  return json<{ status: string }>(
    await fetch(`/api/documents/${docId}/resolve?action=${action}`, { method: "POST" }),
  );
}

export async function getDiff(oldId: string, newId: string): Promise<VersionDiff> {
  return json<VersionDiff>(
    await fetch(`/api/documents/${oldId}/diff/${newId}`, { cache: "no-store" }),
  );
}

export type TranslationItem = {
  block_id: string;
  page: number;
  bbox: number[];
  source: string;
  target: string;
  citations: string[];
};

export type Translation = {
  doc_id: string;
  translator: string;
  count: number;
  items: TranslationItem[];
};

export async function getTranslation(docId: string): Promise<Translation | null> {
  const res = await fetch(`/api/documents/${docId}/translation`, { cache: "no-store" });
  if (res.status === 404) return null;
  return json<Translation>(res);
}

export async function translateDocument(docId: string, force = false): Promise<Translation> {
  await json<unknown>(
    await fetch(`/api/documents/${docId}/translate?force=${force}`, { method: "POST" }),
  );
  const result = await getTranslation(docId);
  if (!result) throw new Error("译文生成失败");
  return result;
}

export type GraphNode = {
  id: string;
  label: string;
  year: number | null;
  in_library: boolean;
  degree_in: number;
  degree_out: number;
  pagerank: number;
  betweenness: number;
  role: "foundational" | "bridge" | "derivative" | "normal";
  page_count: number;
};

export type GraphPayload = {
  nodes: GraphNode[];
  edges: { source: string; target: string; kind: string }[];
  stats: {
    documents: number;
    nodes: number;
    edges: number;
    internal_edges: number;
    density: number;
    is_dag: boolean;
    components: number;
  };
};

export type SurveyPayload = {
  summary: string;
  foundational: { id: string; label: string; pagerank: number; degree_in: number }[];
  future_work: { doc_id: string; title: string; page: number; text: string }[];
};

export async function getGraph(): Promise<GraphPayload> {
  return json<GraphPayload>(await fetch("/api/graph", { cache: "no-store" }));
}

export async function getSurvey(): Promise<SurveyPayload> {
  return json<SurveyPayload>(await fetch("/api/graph/survey", { cache: "no-store" }));
}
