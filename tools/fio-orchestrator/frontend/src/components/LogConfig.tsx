import React from "react";
import { useStore } from "../store";
import type {
  BlktraceCollector, CollectorConfig, CustomCollector, DmesgCollector,
  IostatCollector, LogCollectStepConfig, PerfRecordCollector, PerfStatCollector,
} from "../types";
import { Plus, Trash2 } from "lucide-react";

function Inp({ label, value, onChange, type = "text", placeholder, className = "" }: {
  label: string; value: string | number | undefined; onChange: (v: string) => void;
  type?: string; placeholder?: string; className?: string;
}) {
  return (
    <label className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xs text-gray-500">{label}</span>
      <input
        type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-emerald-400"
      />
    </label>
  );
}

function Sel({ label, value, options, onChange }: {
  label: string; value: string | undefined; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-xs text-gray-500">{label}</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)}
        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-emerald-400 bg-white">
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

// ─────────────────── Individual collector editors ─────────────────────────

function IostatEditor({ cfg, onChange }: { cfg: IostatCollector; onChange: (c: CollectorConfig) => void }) {
  return (
    <div className="space-y-2">
      <Inp label="Devices (comma-sep, empty=all)" value={cfg.devices.join(",")}
        onChange={(v) => onChange({ ...cfg, devices: v ? v.split(",").map(s => s.trim()) : [] })} />
      <div className="grid grid-cols-2 gap-2">
        <Inp label="Interval (s)" value={cfg.interval} type="number"
          onChange={(v) => onChange({ ...cfg, interval: Number(v) })} />
        <Inp label="Count (empty=until stop)" value={cfg.count ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, count: v ? Number(v) : undefined })} />
      </div>
    </div>
  );
}

function BlktraceEditor({ cfg, onChange }: { cfg: BlktraceCollector; onChange: (c: CollectorConfig) => void }) {
  return (
    <div className="space-y-2">
      <Inp label="Devices (comma-sep)" value={cfg.devices.join(",")}
        onChange={(v) => onChange({ ...cfg, devices: v.split(",").map(s => s.trim()) })}
        placeholder="/dev/sda,/dev/nvme0n1" />
      <Inp label="Duration (s, empty=until stop)" value={cfg.duration ?? ""}
        type="number" onChange={(v) => onChange({ ...cfg, duration: v ? Number(v) : undefined })} />
    </div>
  );
}

function PerfStatEditor({ cfg, onChange }: { cfg: PerfStatCollector; onChange: (c: CollectorConfig) => void }) {
  return (
    <div className="space-y-2">
      <Inp label="Events (comma-sep)" value={cfg.events.join(",")}
        onChange={(v) => onChange({ ...cfg, events: v.split(",").map(s => s.trim()) })}
        placeholder="cycles,instructions,cache-misses" />
      <div className="grid grid-cols-2 gap-2">
        <Inp label="PID (empty=system-wide)" value={cfg.pid ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, pid: v ? Number(v) : undefined })} />
        <Inp label="CPU (e.g. 0-3)" value={cfg.cpu ?? ""}
          onChange={(v) => onChange({ ...cfg, cpu: v || undefined })} />
        <Inp label="Duration (s)" value={cfg.duration ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, duration: v ? Number(v) : undefined })} />
      </div>
    </div>
  );
}

function PerfRecordEditor({ cfg, onChange }: { cfg: PerfRecordCollector; onChange: (c: CollectorConfig) => void }) {
  return (
    <div className="space-y-2">
      <Inp label="Events (comma-sep)" value={cfg.events.join(",")}
        onChange={(v) => onChange({ ...cfg, events: v.split(",").map(s => s.trim()) })}
        placeholder="cycles" />
      <div className="grid grid-cols-2 gap-2">
        <Inp label="Frequency (Hz)" value={cfg.frequency} type="number"
          onChange={(v) => onChange({ ...cfg, frequency: Number(v) })} />
        <Inp label="Duration (s)" value={cfg.duration ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, duration: v ? Number(v) : undefined })} />
        <Inp label="PID" value={cfg.pid ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, pid: v ? Number(v) : undefined })} />
        <Inp label="CPU" value={cfg.cpu ?? ""}
          onChange={(v) => onChange({ ...cfg, cpu: v || undefined })} />
      </div>
    </div>
  );
}

function DmesgEditor({ cfg, onChange }: { cfg: DmesgCollector; onChange: (c: CollectorConfig) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input type="checkbox" checked={cfg.clear_before}
        onChange={(e) => onChange({ ...cfg, clear_before: e.target.checked })} />
      <span className="text-xs text-gray-600">Clear dmesg buffer before snapshot</span>
    </label>
  );
}

function CustomEditor({ cfg, onChange }: { cfg: CustomCollector; onChange: (c: CollectorConfig) => void }) {
  const envStr = Object.entries(cfg.env).map(([k, v]) => `${k}=${v}`).join("\n");
  return (
    <div className="space-y-2">
      <Inp label="Label (used in filename)" value={cfg.label}
        onChange={(v) => onChange({ ...cfg, label: v })} placeholder="my_check" />
      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-gray-500">Shell command</span>
        <textarea value={cfg.command} onChange={(e) => onChange({ ...cfg, command: e.target.value })}
          className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-amber-400 font-mono h-20 resize-none"
          placeholder="cat /proc/diskstats" />
      </label>
      <div className="grid grid-cols-2 gap-2">
        <Inp label="Timeout (s)" value={cfg.timeout ?? ""} type="number"
          onChange={(v) => onChange({ ...cfg, timeout: v ? Number(v) : undefined })} />
        <Inp label="Working dir" value={cfg.working_dir ?? ""}
          onChange={(v) => onChange({ ...cfg, working_dir: v || undefined })} />
      </div>
      <label className="flex flex-col gap-0.5">
        <span className="text-xs text-gray-500">Env vars (KEY=VALUE per line)</span>
        <textarea value={envStr}
          onChange={(e) => {
            const env: Record<string, string> = {};
            e.target.value.split("\n").forEach(line => {
              const [k, ...rest] = line.split("=");
              if (k.trim()) env[k.trim()] = rest.join("=").trim();
            });
            onChange({ ...cfg, env });
          }}
          className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-amber-400 font-mono h-16 resize-none"
          placeholder="MY_VAR=value" />
      </label>
    </div>
  );
}

// ────────────────── Collector card ─────────────────────────────────────────

const COLLECTOR_TYPES = ["iostat", "blktrace", "perf_stat", "perf_record", "dmesg", "custom"];
const TYPE_LABELS: Record<string, string> = {
  iostat: "iostat -x", blktrace: "blktrace", perf_stat: "perf stat",
  perf_record: "perf record", dmesg: "dmesg snapshot", custom: "Custom command",
};

function defaultCollector(type: string): CollectorConfig {
  switch (type) {
    case "iostat":     return { type: "iostat", devices: [], interval: 1 };
    case "blktrace":   return { type: "blktrace", devices: [] };
    case "perf_stat":  return { type: "perf_stat", events: ["cycles", "instructions", "cache-misses"] };
    case "perf_record":return { type: "perf_record", events: ["cycles"], frequency: 99 };
    case "dmesg":      return { type: "dmesg", clear_before: false };
    default:           return { type: "custom", command: "", label: "custom", env: {} };
  }
}

function CollectorCard({ col, onChange, onRemove }: {
  col: CollectorConfig; onChange: (c: CollectorConfig) => void; onRemove: () => void;
}) {
  return (
    <div className="border border-emerald-200 rounded-lg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <select value={col.type}
          onChange={(e) => onChange(defaultCollector(e.target.value))}
          className="text-xs font-semibold border-0 bg-transparent focus:outline-none text-emerald-700">
          {COLLECTOR_TYPES.map(t => <option key={t} value={t}>{TYPE_LABELS[t]}</option>)}
        </select>
        <button onClick={onRemove} className="text-red-400 hover:text-red-600"><Trash2 size={13} /></button>
      </div>
      {col.type === "iostat"      && <IostatEditor     cfg={col} onChange={onChange} />}
      {col.type === "blktrace"    && <BlktraceEditor   cfg={col} onChange={onChange} />}
      {col.type === "perf_stat"   && <PerfStatEditor   cfg={col} onChange={onChange} />}
      {col.type === "perf_record" && <PerfRecordEditor cfg={col} onChange={onChange} />}
      {col.type === "dmesg"       && <DmesgEditor      cfg={col} onChange={onChange} />}
      {col.type === "custom"      && <CustomEditor     cfg={col as CustomCollector} onChange={onChange} />}
    </div>
  );
}

// ─────────────────────── Main LogConfig panel ─────────────────────────────

export default function LogConfig() {
  const { activeFlow, setActiveFlow, selectedStepId } = useStore();
  const step = activeFlow?.steps.find((s) => s.id === selectedStepId);
  if (!step || step.type !== "log_collect") {
    return <div className="p-4 text-sm text-gray-400">Select a Log Collect node to configure it.</div>;
  }

  const cfg = step.config as LogCollectStepConfig;

  function update(newCfg: LogCollectStepConfig) {
    if (!activeFlow) return;
    setActiveFlow({ ...activeFlow, steps: activeFlow.steps.map(s => s.id === step.id ? { ...s, config: newCfg } : s) });
  }

  function updateName(name: string) {
    if (!activeFlow) return;
    setActiveFlow({ ...activeFlow, steps: activeFlow.steps.map(s => s.id === step.id ? { ...s, name } : s) });
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-emerald-50">
        <input value={step.name} onChange={(e) => updateName(e.target.value)}
          className="text-sm font-semibold bg-transparent border-b border-emerald-200 focus:outline-none focus:border-emerald-500 w-full" />
        <p className="text-xs text-emerald-600 mt-0.5">Log Collection Configuration</p>
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Inp label="Overall duration (s, empty=until done)" value={cfg.duration ?? ""}
            type="number" onChange={(v) => update({ ...cfg, duration: v ? Number(v) : undefined })}
            className="col-span-2" />
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Collectors ({cfg.collectors.length}) — run concurrently
          </p>
          <button onClick={() => update({ ...cfg, collectors: [...cfg.collectors, defaultCollector("iostat")] })}
            className="flex items-center gap-1 text-xs text-emerald-600 hover:text-emerald-800 font-medium">
            <Plus size={12} /> Add
          </button>
        </div>

        {cfg.collectors.map((col, i) => (
          <CollectorCard key={i} col={col}
            onChange={(c) => update({ ...cfg, collectors: cfg.collectors.map((x, j) => j === i ? c : x) })}
            onRemove={() => update({ ...cfg, collectors: cfg.collectors.filter((_, j) => j !== i) })} />
        ))}
      </div>
    </div>
  );
}
