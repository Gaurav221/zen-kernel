import type { Flow, RunRecord, StepSummary, Template } from "./types";

const BASE = "/api";

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${res.status}: ${txt}`);
  }
  return res.json();
}

// ── Flows ──────────────────────────────────────────────────────────────────
export const listFlows = () => request<Flow[]>("/flows");
export const getFlow   = (id: string) => request<Flow>(`/flows/${id}`);
export const createFlow = (flow: Flow) =>
  request<Flow>("/flows", { method: "POST", body: JSON.stringify(flow) });
export const updateFlow = (id: string, flow: Flow) =>
  request<Flow>(`/flows/${id}`, { method: "PUT", body: JSON.stringify(flow) });
export const deleteFlow = (id: string) =>
  request<void>(`/flows/${id}`, { method: "DELETE" });

// ── Templates ─────────────────────────────────────────────────────────────
export const listTemplates = () => request<Template[]>("/templates");

// ── Runs ──────────────────────────────────────────────────────────────────
export const runFlow = (flowId: string, outputDir?: string) =>
  request<RunRecord>(`/flows/${flowId}/run`, {
    method: "POST",
    body: outputDir ? JSON.stringify({ output_dir: outputDir }) : undefined,
  });
export const cancelRun = (runId: string) =>
  request<RunRecord>(`/runs/${runId}/cancel`, { method: "POST" });
export const listRuns = (flowId?: string) =>
  request<RunRecord[]>(`/runs${flowId ? `?flow_id=${flowId}` : ""}`);
export const getRun = (id: string) => request<RunRecord>(`/runs/${id}`);
export const getRunSummary = (id: string) =>
  request<{ run_id: string; steps: StepSummary[] }>(`/runs/${id}/summary`);

// ── Export ────────────────────────────────────────────────────────────────
export async function exportFlow(
  flow: Flow,
  format: "bash" | "python" | "both",
  outputDir: string,
): Promise<void> {
  const res = await fetch(BASE + "/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ flow, format, output_dir: outputDir }),
  });
  if (!res.ok) throw new Error(await res.text());
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${flow.name.replace(/\s+/g, "_")}_fio_scripts.zip`;
  a.click();
  URL.revokeObjectURL(url);
}

export async function previewExport(
  flow: Flow,
  format: "bash" | "python" | "both",
  outputDir: string,
): Promise<{ path: string; content: string }[]> {
  return request("/export/preview", {
    method: "POST",
    body: JSON.stringify({ flow, format, output_dir: outputDir }),
  });
}
