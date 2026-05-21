import React, { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { cancelRun, getRun, listRuns, runFlow } from "../api";
import type { RunRecord, WsMessage } from "../types";
import {
  Play, Square, RefreshCw, ChevronRight, ChevronDown, Circle,
  CheckCircle2, XCircle, Clock, AlertCircle,
} from "lucide-react";

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "done":     return <CheckCircle2 size={14} className="text-green-500" />;
    case "error":    return <XCircle size={14} className="text-red-500" />;
    case "running":  return <RefreshCw size={14} className="text-blue-500 animate-spin" />;
    case "pending":  return <Clock size={14} className="text-gray-400" />;
    case "cancelled":return <AlertCircle size={14} className="text-orange-400" />;
    default:         return <Circle size={14} className="text-gray-300" />;
  }
}

function StepRow({ step, logs }: { step: RunRecord["steps"][0]; logs: WsMessage[] }) {
  const [open, setOpen] = useState(false);
  const myLogs = logs.filter((m) => m.step_id === step.step_id && m.type === "log");
  const duration = step.started_at && step.finished_at
    ? ((new Date(step.finished_at).getTime() - new Date(step.started_at).getTime()) / 1000).toFixed(1) + "s"
    : step.started_at ? "running…" : "";

  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <StatusIcon status={step.status} />
        <span className="text-xs font-medium text-gray-800 flex-1">{step.step_name}</span>
        <span className="text-xs text-gray-400">{duration}</span>
        {myLogs.length > 0 && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
      </button>
      {open && myLogs.length > 0 && (
        <div className="bg-gray-900 text-gray-100 font-mono text-xs px-3 py-2 max-h-48 overflow-y-auto">
          {myLogs.map((m, i) => (
            <div key={i} className="leading-5 whitespace-pre-wrap">{String(m.data)}</div>
          ))}
        </div>
      )}
      {step.error && (
        <div className="px-3 py-1 text-xs text-red-600 bg-red-50">{step.error}</div>
      )}
    </div>
  );
}

export default function RunPanel() {
  const { activeFlow, activeRun, setActiveRun, runs, setRuns, upsertRun, logs, appendLog, clearLogs } = useStore();
  const [running, setRunning] = useState(false);
  const [outputDir, setOutputDir] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (activeFlow) {
      listRuns(activeFlow.id).then(setRuns).catch(console.error);
    }
  }, [activeFlow?.id]);

  const allLogs = activeRun ? (logs[activeRun.id] ?? []) : [];
  const terminalLogs = allLogs.filter((m) => m.type === "log");

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [terminalLogs.length]);

  function connectWs(runId: string) {
    if (wsRef.current) { wsRef.current.close(); }
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/runs/${runId}`);
    ws.onmessage = (e) => {
      const msg: WsMessage = JSON.parse(e.data);
      appendLog(runId, msg);
      if (msg.type === "step_done" || msg.type === "run_done") {
        getRun(runId).then((r) => { upsertRun(r); setActiveRun(r); });
      }
      if (msg.type === "run_done") {
        setRunning(false);
        ws.close();
      }
    };
    wsRef.current = ws;
  }

  async function startRun() {
    if (!activeFlow) return;
    setRunning(true);
    clearLogs("__new__");
    try {
      const run = await runFlow(activeFlow.id, outputDir || undefined);
      upsertRun(run);
      setActiveRun(run);
      clearLogs(run.id);
      connectWs(run.id);
    } catch (e) {
      setRunning(false);
      alert("Failed to start run: " + String(e));
    }
  }

  async function stopRun() {
    if (!activeRun) return;
    await cancelRun(activeRun.id);
    setRunning(false);
    wsRef.current?.close();
    const updated = await getRun(activeRun.id);
    upsertRun(updated);
    setActiveRun(updated);
  }

  function selectRun(run: RunRecord) {
    setActiveRun(run);
    if (run.status === "running" && !wsRef.current) {
      setRunning(true);
      connectWs(run.id);
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
        <p className="text-sm font-semibold text-gray-700">Run Controls</p>
      </div>

      <div className="p-3 border-b border-gray-100 space-y-2">
        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-gray-500">Output dir (empty = ./results/TIMESTAMP)</span>
          <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-blue-400"
            placeholder="./results" />
        </label>

        <div className="flex gap-2">
          <button onClick={startRun} disabled={!activeFlow || running}
            className="flex-1 flex items-center justify-center gap-2 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold disabled:opacity-40 disabled:cursor-not-allowed">
            <Play size={13} /> Run Flow
          </button>
          {running && (
            <button onClick={stopRun}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md bg-red-100 hover:bg-red-200 text-red-700 text-xs font-semibold">
              <Square size={13} /> Cancel
            </button>
          )}
        </div>
      </div>

      {/* Active run progress */}
      {activeRun && (
        <div className="border-b border-gray-100">
          <div className="px-3 py-2 flex items-center gap-2 bg-gray-50">
            <StatusIcon status={activeRun.status} />
            <span className="text-xs font-medium text-gray-700 flex-1 truncate">
              {activeRun.flow_name}
            </span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
              activeRun.status === "done" ? "bg-green-100 text-green-700"
              : activeRun.status === "error" ? "bg-red-100 text-red-700"
              : activeRun.status === "running" ? "bg-blue-100 text-blue-700"
              : "bg-gray-100 text-gray-600"
            }`}>
              {activeRun.status}
            </span>
          </div>
          <div className="px-3 pb-2 space-y-1 max-h-48 overflow-y-auto">
            {activeRun.steps.map((s) => (
              <StepRow key={s.step_id} step={s} logs={allLogs} />
            ))}
          </div>
        </div>
      )}

      {/* Live terminal */}
      {activeRun && terminalLogs.length > 0 && (
        <div className="flex-1 overflow-hidden flex flex-col">
          <div className="px-3 py-1.5 bg-gray-900 flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-red-500" />
            <div className="w-2 h-2 rounded-full bg-yellow-500" />
            <div className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-xs text-gray-400 ml-1 font-mono">live output</span>
          </div>
          <div className="flex-1 bg-gray-950 text-gray-200 font-mono text-xs px-3 py-2 overflow-y-auto">
            {terminalLogs.map((m, i) => (
              <div key={i} className="leading-5 whitespace-pre-wrap">{String(m.data)}</div>
            ))}
            <div ref={logEndRef} />
          </div>
        </div>
      )}

      {/* Run history */}
      {runs.length > 0 && (
        <div className="border-t border-gray-100 flex-shrink-0">
          <p className="text-xs text-gray-500 font-semibold px-3 py-2 uppercase tracking-wide">
            History
          </p>
          <div className="max-h-40 overflow-y-auto">
            {runs.slice(0, 15).map((r) => (
              <button key={r.id} onClick={() => selectRun(r)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-gray-50 ${activeRun?.id === r.id ? "bg-blue-50" : ""}`}>
                <StatusIcon status={r.status} />
                <span className="text-xs text-gray-700 flex-1 truncate">{r.flow_name}</span>
                <span className="text-xs text-gray-400 font-mono shrink-0">
                  {new Date(r.started_at).toLocaleTimeString()}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
