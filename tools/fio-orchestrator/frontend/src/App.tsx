import React, { useEffect, useState } from "react";
import { useStore } from "./store";
import { createFlow, deleteFlow, listFlows, updateFlow } from "./api";
import type { Flow } from "./types";
import FlowEditor from "./components/FlowEditor";
import FioConfig from "./components/FioConfig";
import LogConfig from "./components/LogConfig";
import CmdConfig from "./components/CmdConfig";
import Templates from "./components/Templates";
import RunPanel from "./components/RunPanel";
import Analysis from "./components/Analysis";
import ExportPanel from "./components/ExportPanel";
import {
  Zap, LayoutTemplate, Play, BarChart2, Download, Plus, Trash2,
  Save, Edit3, FolderOpen, Activity,
} from "lucide-react";

function newFlow(): Flow {
  return {
    id: Math.random().toString(36).slice(2),
    name: "New Flow",
    description: "",
    steps: [],
    edges: [],
    output_dir: "./results",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

// ─────────────────────── Left sidebar: flow library ───────────────────────

function FlowLibrary() {
  const { flows, setFlows, activeFlow, setActiveFlow, removeFlow } = useStore();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [savePending, setSavePending] = useState(false);

  useEffect(() => {
    listFlows().then(setFlows).catch(console.error);
  }, []);

  async function create() {
    const f = newFlow();
    const saved = await createFlow(f);
    setFlows([saved, ...flows]);
    setActiveFlow(saved);
  }

  async function save() {
    if (!activeFlow) return;
    setSavePending(true);
    try {
      const saved = await updateFlow(activeFlow.id, activeFlow);
      setFlows(flows.map((f) => (f.id === saved.id ? saved : f)));
      setActiveFlow(saved);
    } finally {
      setSavePending(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this flow?")) return;
    await deleteFlow(id);
    removeFlow(id);
  }

  return (
    <div className="w-56 flex-shrink-0 border-r border-gray-200 bg-gray-50 flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-gray-200 flex items-center gap-2">
        <Zap size={16} className="text-blue-600" />
        <span className="font-bold text-gray-800 text-sm">FIO Orchestrator</span>
      </div>

      {/* Actions */}
      <div className="px-3 py-2 border-b border-gray-100 flex gap-1.5">
        <button onClick={create}
          className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-md text-xs font-medium">
          <Plus size={11} /> New
        </button>
        {activeFlow && (
          <button onClick={save} disabled={savePending}
            className="flex-1 flex items-center justify-center gap-1 py-1.5 bg-white border border-gray-200 hover:border-blue-300 text-gray-600 hover:text-blue-600 rounded-md text-xs font-medium disabled:opacity-40">
            <Save size={11} /> Save
          </button>
        )}
      </div>

      {/* Flow list */}
      <div className="flex-1 overflow-y-auto py-1">
        {flows.length === 0 && (
          <div className="px-3 py-4 text-xs text-gray-400 text-center">
            No flows yet. Click New to start.
          </div>
        )}
        {flows.map((flow) => (
          <div key={flow.id}
            className={`group flex items-center gap-1 px-3 py-2 cursor-pointer ${
              activeFlow?.id === flow.id ? "bg-blue-50 border-l-2 border-blue-500" : "hover:bg-gray-100"
            }`}
            onClick={() => setActiveFlow(flow)}
          >
            {editingId === flow.id ? (
              <input
                autoFocus
                value={activeFlow?.id === flow.id ? activeFlow.name : flow.name}
                onChange={(e) => {
                  if (activeFlow?.id === flow.id) {
                    setActiveFlow({ ...activeFlow, name: e.target.value });
                  }
                }}
                onBlur={() => setEditingId(null)}
                onKeyDown={(e) => e.key === "Enter" && setEditingId(null)}
                className="flex-1 text-xs border border-blue-300 rounded px-1 py-0.5 focus:outline-none"
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span className="flex-1 text-xs text-gray-700 truncate">
                {activeFlow?.id === flow.id ? activeFlow.name : flow.name}
              </span>
            )}
            <button
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-blue-600 p-0.5"
              onClick={(e) => { e.stopPropagation(); setEditingId(flow.id); setActiveFlow(flow); }}
            >
              <Edit3 size={10} />
            </button>
            <button
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-600 p-0.5"
              onClick={(e) => { e.stopPropagation(); remove(flow.id); }}
            >
              <Trash2 size={10} />
            </button>
          </div>
        ))}
      </div>

      {/* Output dir */}
      {activeFlow && (
        <div className="px-3 py-2 border-t border-gray-100">
          <label className="flex flex-col gap-0.5">
            <span className="text-xs text-gray-400">Output dir</span>
            <input
              value={activeFlow.output_dir}
              onChange={(e) => setActiveFlow({ ...activeFlow, output_dir: e.target.value })}
              className="text-xs border border-gray-200 rounded px-2 py-1 font-mono focus:outline-none focus:ring-1 focus:ring-blue-300"
            />
          </label>
          <label className="flex flex-col gap-0.5 mt-1.5">
            <span className="text-xs text-gray-400">Description</span>
            <input
              value={activeFlow.description}
              onChange={(e) => setActiveFlow({ ...activeFlow, description: e.target.value })}
              className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-300"
              placeholder="Optional description"
            />
          </label>
        </div>
      )}
    </div>
  );
}

// ──────────────────── Right panel: tabbed configuration ───────────────────

type RightTab = "templates" | "config" | "run" | "analysis" | "export";

const RIGHT_TABS: { id: RightTab; label: string; icon: React.ReactNode }[] = [
  { id: "templates", label: "Templates", icon: <LayoutTemplate size={13} /> },
  { id: "config",    label: "Configure", icon: <Activity size={13} /> },
  { id: "run",       label: "Run",       icon: <Play size={13} /> },
  { id: "analysis",  label: "Analysis",  icon: <BarChart2 size={13} /> },
  { id: "export",    label: "Export",    icon: <Download size={13} /> },
];

function RightPanel() {
  const { rightPanel, selectedStepId, activeFlow } = useStore();
  const [tab, setTab] = useState<RightTab>("templates");

  // Auto-switch to config tab when a node is selected
  useEffect(() => {
    if (selectedStepId && rightPanel) {
      setTab("config");
    }
  }, [selectedStepId, rightPanel]);

  return (
    <div className="w-80 flex-shrink-0 border-l border-gray-200 bg-white flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 overflow-x-auto">
        {RIGHT_TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium whitespace-nowrap border-b-2 ${
              tab === t.id
                ? "border-blue-500 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}>
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Panel body */}
      <div className="flex-1 overflow-hidden flex flex-col">
        {tab === "templates" && <Templates />}
        {tab === "config" && (
          <>
            {rightPanel === "fio-config"  && <FioConfig />}
            {rightPanel === "log-config"  && <LogConfig />}
            {rightPanel === "cmd-config"  && <CmdConfig />}
            {!rightPanel && (
              <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                Click a node to configure it
              </div>
            )}
          </>
        )}
        {tab === "run"      && <RunPanel />}
        {tab === "analysis" && <Analysis />}
        {tab === "export"   && <ExportPanel />}
      </div>
    </div>
  );
}

// ─────────────────────────── Main App ─────────────────────────────────────

export default function App() {
  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <FlowLibrary />
      <FlowEditor />
      <RightPanel />
    </div>
  );
}
