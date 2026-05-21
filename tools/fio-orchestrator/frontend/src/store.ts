import { create } from "zustand";
import type { Flow, RunRecord, StepStatus, Template, WsMessage } from "./types";

interface AppState {
  // Flows
  flows: Flow[];
  activeFlow: Flow | null;
  setFlows: (flows: Flow[]) => void;
  setActiveFlow: (flow: Flow | null) => void;
  upsertFlow: (flow: Flow) => void;
  removeFlow: (id: string) => void;

  // Templates
  templates: Template[];
  setTemplates: (t: Template[]) => void;

  // Runs
  runs: RunRecord[];
  activeRun: RunRecord | null;
  setRuns: (runs: RunRecord[]) => void;
  setActiveRun: (run: RunRecord | null) => void;
  upsertRun: (run: RunRecord) => void;

  // Live logs (keyed by run_id → messages)
  logs: Record<string, WsMessage[]>;
  appendLog: (runId: string, msg: WsMessage) => void;
  clearLogs: (runId: string) => void;

  // UI panel state
  rightPanel: "fio-config" | "log-config" | "cmd-config" | "analysis" | "export" | null;
  setRightPanel: (p: AppState["rightPanel"]) => void;
  selectedStepId: string | null;
  setSelectedStepId: (id: string | null) => void;
}

export const useStore = create<AppState>((set) => ({
  flows: [],
  activeFlow: null,
  setFlows: (flows) => set({ flows }),
  setActiveFlow: (flow) => set({ activeFlow: flow }),
  upsertFlow: (flow) =>
    set((s) => ({
      flows: s.flows.some((f) => f.id === flow.id)
        ? s.flows.map((f) => (f.id === flow.id ? flow : f))
        : [flow, ...s.flows],
      activeFlow: s.activeFlow?.id === flow.id ? flow : s.activeFlow,
    })),
  removeFlow: (id) =>
    set((s) => ({
      flows: s.flows.filter((f) => f.id !== id),
      activeFlow: s.activeFlow?.id === id ? null : s.activeFlow,
    })),

  templates: [],
  setTemplates: (templates) => set({ templates }),

  runs: [],
  activeRun: null,
  setRuns: (runs) => set({ runs }),
  setActiveRun: (run) => set({ activeRun: run }),
  upsertRun: (run) =>
    set((s) => ({
      runs: s.runs.some((r) => r.id === run.id)
        ? s.runs.map((r) => (r.id === run.id ? run : r))
        : [run, ...s.runs],
      activeRun: s.activeRun?.id === run.id ? run : s.activeRun,
    })),

  logs: {},
  appendLog: (runId, msg) =>
    set((s) => ({
      logs: {
        ...s.logs,
        [runId]: [...(s.logs[runId] ?? []).slice(-2000), msg],
      },
    })),
  clearLogs: (runId) =>
    set((s) => ({ logs: { ...s.logs, [runId]: [] } })),

  rightPanel: null,
  setRightPanel: (rightPanel) => set({ rightPanel }),
  selectedStepId: null,
  setSelectedStepId: (selectedStepId) => set({ selectedStepId }),
}));
