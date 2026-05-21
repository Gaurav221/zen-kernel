import React, { useEffect, useState } from "react";
import { useStore } from "../store";
import { getRunSummary } from "../api";
import type { FioJobSummary, StepSummary, TimeseriesPoint } from "../types";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, BarChart, Bar,
} from "recharts";
import { BarChart2, Activity, Clock } from "lucide-react";

function fmt(v: number, unit: string, decimals = 1) {
  return `${v.toFixed(decimals)}${unit}`;
}

// ──────────────────────── Summary table ───────────────────────────────────

function JobSummaryTable({ jobs }: { jobs: FioJobSummary[] }) {
  const rows: React.ReactNode[] = [];
  for (const job of jobs) {
    for (const dir of ["read", "write"] as const) {
      const d = job[dir];
      if (!d) continue;
      rows.push(
        <tr key={`${job.job_name}-${dir}`} className="hover:bg-gray-50">
          <td className="px-3 py-1.5 text-xs font-mono font-medium text-gray-700">{job.job_name}</td>
          <td className={`px-2 py-1.5 text-xs font-semibold ${dir === "read" ? "text-blue-600" : "text-orange-600"}`}>
            {dir}
          </td>
          <td className="px-2 py-1.5 text-xs text-right text-gray-800 font-mono">{fmt(d.iops, "")}</td>
          <td className="px-2 py-1.5 text-xs text-right text-gray-800 font-mono">{fmt(d.bw_mbps, " MB/s")}</td>
          <td className="px-2 py-1.5 text-xs text-right text-gray-600 font-mono">{fmt(d.lat_mean_us, " µs")}</td>
          <td className="px-2 py-1.5 text-xs text-right text-gray-600 font-mono">{fmt(d.clat_p50_us, " µs")}</td>
          <td className="px-2 py-1.5 text-xs text-right text-gray-600 font-mono">{fmt(d.clat_p99_us, " µs")}</td>
          <td className="px-2 py-1.5 text-xs text-right text-red-600 font-mono">{fmt(d.clat_p999_us, " µs")}</td>
        </tr>,
      );
    }
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="w-full border-collapse">
        <thead>
          <tr className="bg-gray-50">
            {["Job", "Dir", "IOPS", "BW", "Lat mean", "p50", "p99", "p99.9"].map((h) => (
              <th key={h} className="px-2 py-2 text-left text-xs font-semibold text-gray-500 whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">{rows}</tbody>
      </table>
    </div>
  );
}

// ──────────────────────── Time-series charts ──────────────────────────────

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"];

function TimeseriesChart({
  title, data, unit, color,
}: {
  title: string; data: TimeseriesPoint[]; unit: string; color: string;
}) {
  const reads = data.filter((d) => d.dir === 0);
  const writes = data.filter((d) => d.dir === 1);
  const chartData = reads.map((r, i) => ({
    t: (r.time_ms / 1000).toFixed(1),
    read: r.value,
    write: writes[i]?.value,
  }));

  return (
    <div>
      <p className="text-xs font-semibold text-gray-600 mb-2">{title}</p>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={chartData} margin={{ top: 0, right: 10, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="t" tick={{ fontSize: 10 }} label={{ value: "s", position: "insideRight", offset: -5, fontSize: 10 }} />
          <YAxis tick={{ fontSize: 10 }} width={55} tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
          <Tooltip formatter={(v: any) => `${v} ${unit}`} labelFormatter={(l) => `${l}s`} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Line type="monotone" dataKey="read" stroke="#3b82f6" dot={false} strokeWidth={1.5} />
          {writes.length > 0 && <Line type="monotone" dataKey="write" stroke="#f59e0b" dot={false} strokeWidth={1.5} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ──────────────────────── Bar comparison ──────────────────────────────────

function IopsBarChart({ steps }: { steps: StepSummary[] }) {
  const bars: { name: string; read: number; write: number }[] = [];
  for (const step of steps) {
    if (!step.fio_jobs) continue;
    for (const job of step.fio_jobs) {
      bars.push({
        name: `${job.job_name}`,
        read: job.read?.iops ?? 0,
        write: job.write?.iops ?? 0,
      });
    }
  }
  if (!bars.length) return null;
  return (
    <div>
      <p className="text-xs font-semibold text-gray-600 mb-2 flex items-center gap-1.5">
        <BarChart2 size={12} /> IOPS Comparison
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={bars} margin={{ top: 0, right: 10, left: 0, bottom: 30 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="name" tick={{ fontSize: 9 }} angle={-25} textAnchor="end" />
          <YAxis tick={{ fontSize: 10 }} width={55} tickFormatter={(v) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)} />
          <Tooltip formatter={(v: any) => `${v.toFixed(0)} IOPS`} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="read" fill="#3b82f6" name="Read IOPS" />
          <Bar dataKey="write" fill="#f59e0b" name="Write IOPS" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ──────────────────────── Latency percentile ──────────────────────────────

function LatencyChart({ steps }: { steps: StepSummary[] }) {
  const rows: { name: string; p50: number; p99: number; p999: number }[] = [];
  for (const step of steps) {
    if (!step.fio_jobs) continue;
    for (const job of step.fio_jobs) {
      const d = job.read ?? job.write;
      if (!d) continue;
      rows.push({
        name: job.job_name,
        p50: d.clat_p50_us,
        p99: d.clat_p99_us,
        p999: d.clat_p999_us,
      });
    }
  }
  if (!rows.length) return null;
  return (
    <div>
      <p className="text-xs font-semibold text-gray-600 mb-2 flex items-center gap-1.5">
        <Clock size={12} /> Completion Latency (µs)
      </p>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={rows} margin={{ top: 0, right: 10, left: 0, bottom: 30 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="name" tick={{ fontSize: 9 }} angle={-25} textAnchor="end" />
          <YAxis tick={{ fontSize: 10 }} width={60} />
          <Tooltip formatter={(v: any) => `${v.toFixed(1)} µs`} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="p50" fill="#10b981" name="p50" />
          <Bar dataKey="p99" fill="#f59e0b" name="p99" />
          <Bar dataKey="p999" fill="#ef4444" name="p99.9" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────────────────── Main Analysis panel ──────────────────────────────

export default function Analysis() {
  const { activeRun } = useStore();
  const [summary, setSummary] = useState<{ run_id: string; steps: StepSummary[] } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!activeRun || activeRun.status === "running") return;
    setLoading(true);
    getRunSummary(activeRun.id)
      .then(setSummary)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [activeRun?.id, activeRun?.status]);

  if (!activeRun) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Run a flow to see analysis here.
      </div>
    );
  }

  if (activeRun.status === "running") {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        <Activity size={16} className="animate-pulse mr-2" /> Run in progress…
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        Loading results…
      </div>
    );
  }

  if (!summary) return null;

  const stepsWithFio = summary.steps.filter((s) => s.fio_jobs?.length);
  const allJobs = stepsWithFio.flatMap((s) => s.fio_jobs ?? []);

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-6">
      <div>
        <p className="text-xs text-gray-400 font-mono mb-1">run: {activeRun.id}</p>
        <p className="text-sm font-semibold text-gray-700">{activeRun.flow_name}</p>
      </div>

      {allJobs.length > 0 && (
        <>
          <section className="space-y-2">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Summary</p>
            <JobSummaryTable jobs={allJobs} />
          </section>

          <section><IopsBarChart steps={summary.steps} /></section>
          <section><LatencyChart steps={summary.steps} /></section>
        </>
      )}

      {/* Time-series per step */}
      {summary.steps.map((step, si) => {
        if (!step.timeseries || Object.keys(step.timeseries).length === 0) return null;
        return (
          <section key={si} className="space-y-3">
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Time-series — {step.log_dir?.split("/").pop()}
            </p>
            {Object.entries(step.timeseries).map(([name, pts]) => {
              const isBw = name.includes("_bw");
              const isIops = name.includes("_iops");
              const isLat = name.includes("_lat") || name.includes("_clat");
              const unit = isBw ? "KB/s" : isIops ? "IOPS" : isLat ? "ns" : "val";
              return (
                <TimeseriesChart
                  key={name}
                  title={name}
                  data={pts}
                  unit={unit}
                  color={COLORS[si % COLORS.length]}
                />
              );
            })}
          </section>
        );
      })}

      {summary.steps.length === 0 && (
        <p className="text-sm text-gray-400 text-center py-8">No FIO results found in this run.</p>
      )}
    </div>
  );
}
