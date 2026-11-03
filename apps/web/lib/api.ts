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
