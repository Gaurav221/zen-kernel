import React, { useEffect } from "react";
import { useStore } from "../store";
import { listTemplates } from "../api";
import type { FlowStep, Template } from "../types";
import { Zap } from "lucide-react";

const CATEGORY_COLORS: Record<string, string> = {
  IOPS: "bg-blue-100 text-blue-700",
  Throughput: "bg-purple-100 text-purple-700",
  Latency: "bg-orange-100 text-orange-700",
  "io_uring": "bg-indigo-100 text-indigo-700",
  Verification: "bg-green-100 text-green-700",
  Stress: "bg-red-100 text-red-700",
  Scalability: "bg-teal-100 text-teal-700",
};

export default function Templates({ onApply }: { onApply?: (t: Template) => void }) {
  const { templates, setTemplates, activeFlow, setActiveFlow } = useStore();

  useEffect(() => {
    if (templates.length === 0) {
      listTemplates().then(setTemplates).catch(console.error);
    }
  }, []);

  function apply(t: Template) {
    if (!activeFlow) return;
    const id = Math.random().toString(36).slice(2, 10);
    const newStep: FlowStep = {
      id,
      type: "fio",
      name: t.name.replace(/\s+/g, "_").toLowerCase(),
      config: t.config,
      position_x: activeFlow.steps.length * 220,
      position_y: 100,
    };
    setActiveFlow({ ...activeFlow, steps: [...activeFlow.steps, newStep] });
    onApply?.(t);
  }

  const categories = Array.from(new Set(templates.map((t) => t.category)));

  return (
    <div className="p-3 space-y-4 overflow-y-auto h-full">
      <p className="text-xs text-gray-500 font-semibold uppercase tracking-wide">
        Template Library
      </p>
      {categories.map((cat) => (
        <div key={cat}>
          <p className={`text-xs font-semibold px-2 py-0.5 rounded-full inline-block mb-2 ${CATEGORY_COLORS[cat] ?? "bg-gray-100 text-gray-600"}`}>
            {cat}
          </p>
          <div className="space-y-1.5">
            {templates.filter((t) => t.category === cat).map((t) => (
              <div key={t.id}
                className="border border-gray-100 rounded-lg p-2.5 hover:border-blue-300 hover:bg-blue-50 transition-colors cursor-pointer group"
                onClick={() => apply(t)}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-gray-800">{t.name}</span>
                  <Zap size={11} className="text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
                <p className="text-xs text-gray-500 mt-0.5 leading-tight">{t.description}</p>
                {activeFlow && (
                  <button
                    onClick={(e) => { e.stopPropagation(); apply(t); }}
                    className="mt-1.5 text-xs text-blue-600 hover:text-blue-800 font-medium"
                  >
                    Add to flow →
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
