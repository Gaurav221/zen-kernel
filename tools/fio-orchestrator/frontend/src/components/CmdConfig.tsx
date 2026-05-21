import React from "react";
import { useStore } from "../store";
import type { CommandStepConfig } from "../types";

export default function CmdConfig() {
  const { activeFlow, setActiveFlow, selectedStepId } = useStore();
  const step = activeFlow?.steps.find((s) => s.id === selectedStepId);
  if (!step || step.type !== "command") {
    return <div className="p-4 text-sm text-gray-400">Select a Command node to configure it.</div>;
  }
  const cfg = step.config as CommandStepConfig;

  const stepId = step.id;
  function update(newCfg: CommandStepConfig) {
    if (!activeFlow) return;
    setActiveFlow({ ...activeFlow, steps: activeFlow.steps.map(s => s.id === stepId ? { ...s, config: newCfg } : s) });
  }

  function updateName(name: string) {
    if (!activeFlow) return;
    setActiveFlow({ ...activeFlow, steps: activeFlow.steps.map(s => s.id === stepId ? { ...s, name } : s) });
  }

  const envStr = Object.entries(cfg.env).map(([k, v]) => `${k}=${v}`).join("\n");

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-amber-50">
        <input value={step.name} onChange={(e) => updateName(e.target.value)}
          className="text-sm font-semibold bg-transparent border-b border-amber-200 focus:outline-none focus:border-amber-500 w-full" />
        <p className="text-xs text-amber-600 mt-0.5">Shell Command</p>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Label (used in log filename)</span>
          <input value={cfg.label} onChange={(e) => update({ ...cfg, label: e.target.value })}
            className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
            placeholder="my_command" />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Shell command</span>
          <textarea value={cfg.command} onChange={(e) => update({ ...cfg, command: e.target.value })}
            className="text-xs border border-gray-200 rounded px-2 py-2 focus:outline-none focus:ring-1 focus:ring-amber-400 font-mono h-28 resize-none"
            placeholder="cat /proc/diskstats&#10;smartctl -a /dev/sda&#10;lsblk -d -o NAME,MODEL,SIZE" />
        </label>

        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Timeout (s)</span>
            <input type="number" value={cfg.timeout ?? ""} onChange={(e) => update({ ...cfg, timeout: e.target.value ? Number(e.target.value) : undefined })}
              className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
              placeholder="none" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-gray-500">Working dir</span>
            <input value={cfg.working_dir ?? ""} onChange={(e) => update({ ...cfg, working_dir: e.target.value || undefined })}
              className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
              placeholder="/tmp" />
          </label>
        </div>

        <label className="flex flex-col gap-1">
          <span className="text-xs text-gray-500">Env vars (KEY=VALUE per line)</span>
          <textarea value={envStr}
            onChange={(e) => {
              const env: Record<string, string> = {};
              e.target.value.split("\n").forEach(line => {
                const [k, ...rest] = line.split("=");
                if (k.trim()) env[k.trim()] = rest.join("=").trim();
              });
              update({ ...cfg, env });
            }}
            className="text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400 font-mono h-20 resize-none"
            placeholder="MY_VAR=value" />
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={cfg.fail_on_error}
            onChange={(e) => update({ ...cfg, fail_on_error: e.target.checked })} />
          <span className="text-xs text-gray-600">Abort flow on non-zero exit code</span>
        </label>
      </div>
    </div>
  );
}
