import React, { useState } from "react";
import { useStore } from "../store";
import type { FioJob, FioStepConfig, FlowStep } from "../types";
import { Plus, Trash2, ChevronDown, ChevronRight, GripVertical } from "lucide-react";

// ─────────────────────── Tiny helpers ─────────────────────────────────────

function Inp({
  label, value, onChange, type = "text", placeholder, className = "",
}: {
  label: string; value: string | number | undefined; onChange: (v: string) => void;
  type?: string; placeholder?: string; className?: string;
}) {
  return (
    <label className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xs text-gray-500">{label}</span>
      <input
        type={type}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
      />
    </label>
  );
}

function Sel({
  label, value, options, onChange,
}: {
  label: string; value: string | undefined; options: string[]; onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-xs text-gray-500">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="text-xs border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
      >
        {options.map((o) => <option key={o} value={o}>{o || "(default)"}</option>)}
      </select>
    </label>
  );
}

function Toggle({
  label, value, onChange,
}: {
  label: string; value: number | undefined; onChange: (v: number | undefined) => void;
}) {
  const checked = value === 1;
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <div
        onClick={() => onChange(checked ? undefined : 1)}
        className={`relative w-8 h-4 rounded-full transition-colors ${checked ? "bg-blue-500" : "bg-gray-300"}`}
      >
        <div className={`absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </div>
      <span className="text-xs text-gray-600">{label}</span>
    </label>
  );
}

function Section({ title, children, defaultOpen = false }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border border-gray-100 rounded-md overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-xs font-semibold text-gray-700"
        onClick={() => setOpen((o) => !o)}
      >
        {title}
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>
      {open && <div className="p-3 grid grid-cols-2 gap-2">{children}</div>}
    </div>
  );
}

// ─────────────────────── Job editor ───────────────────────────────────────

const RW_OPTIONS = [
  "read", "write", "randread", "randwrite", "randrw", "readwrite",
  "trimwrite", "randtrimwrite",
];

const IOENGINES = [
  "libaio", "io_uring", "sync", "psync", "vsync", "mmap", "splice",
  "net", "netsplice", "cpuio", "null",
];

const VERIFY_OPTIONS = ["", "crc32c", "crc32c-intel", "crc32", "crc64", "md5", "sha1", "sha256", "sha512", "xxhash", "meta"];
const RAND_GEN = ["", "tausworthe", "tausworthe64", "lfsr"];
const RAND_DIST = ["", "random", "zipf", "pareto", "normal", "zoned"];
const RATE_PROC = ["", "linear", "poisson"];
const CPU_POLICY = ["", "shared", "split"];
const IO_PRIO_CLASS = ["", "0", "1", "2", "3"];

function JobEditor({
  job, onChange, onRemove, showRemove,
}: {
  job: FioJob; onChange: (j: FioJob) => void; onRemove: () => void; showRemove: boolean;
}) {
  function up(key: keyof FioJob, val: any) {
    onChange({ ...job, [key]: val === "" ? undefined : isNaN(Number(val)) ? val : val });
  }
  function upNum(key: keyof FioJob, val: string) {
    onChange({ ...job, [key]: val === "" ? undefined : Number(val) });
  }

  return (
    <div className="border border-blue-200 rounded-lg p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GripVertical size={14} className="text-gray-400" />
          <input
            value={job.name}
            onChange={(e) => up("name", e.target.value)}
            className="text-sm font-semibold border-b border-transparent hover:border-gray-300 focus:border-blue-400 focus:outline-none bg-transparent"
          />
          <Toggle label="stonewall" value={job.stonewall} onChange={(v) => onChange({ ...job, stonewall: v })} />
        </div>
        {showRemove && (
          <button onClick={onRemove} className="text-red-400 hover:text-red-600">
            <Trash2 size={13} />
          </button>
        )}
      </div>

      <Section title="Workload" defaultOpen>
        <Sel label="rw" value={job.rw} options={RW_OPTIONS} onChange={(v) => up("rw", v)} />
        <Inp label="bs" value={job.bs} onChange={(v) => up("bs", v)} placeholder="4k" />
        {(job.rw === "randrw" || job.rw === "readwrite") && (
          <>
            <Inp label="rwmixread %" value={job.rwmixread} onChange={(v) => upNum("rwmixread", v)} type="number" />
            <Inp label="rwmixwrite %" value={job.rwmixwrite} onChange={(v) => upNum("rwmixwrite", v)} type="number" />
          </>
        )}
        <Inp label="iodepth" value={job.iodepth} onChange={(v) => upNum("iodepth", v)} type="number" />
        <Inp label="numjobs" value={job.numjobs} onChange={(v) => upNum("numjobs", v)} type="number" placeholder="(global)" />
        <Inp label="bsrange" value={job.bsrange} onChange={(v) => up("bsrange", v)} placeholder="4k-64k" />
        <Inp label="bssplit" value={job.bssplit} onChange={(v) => up("bssplit", v)} placeholder="4k/50:8k/50" />
      </Section>

      <Section title="Target">
        <Inp label="filename" value={job.filename} onChange={(v) => up("filename", v)} placeholder="/dev/sda" className="col-span-2" />
        <Inp label="directory" value={job.directory} onChange={(v) => up("directory", v)} placeholder="/mnt/test" className="col-span-2" />
        <Inp label="size" value={job.size} onChange={(v) => up("size", v)} placeholder="1g" />
        <Inp label="io_size" value={job.io_size} onChange={(v) => up("io_size", v)} placeholder="100%" />
        <Inp label="filesize" value={job.filesize} onChange={(v) => up("filesize", v)} placeholder="1g" />
        <Inp label="nrfiles" value={job.nrfiles} onChange={(v) => upNum("nrfiles", v)} type="number" />
        <Inp label="openfiles" value={job.openfiles} onChange={(v) => upNum("openfiles", v)} type="number" />
        <Toggle label="fill_device" value={job.fill_device} onChange={(v) => onChange({ ...job, fill_device: v })} />
      </Section>

      <Section title="Timing">
        <Inp label="runtime (s)" value={job.runtime} onChange={(v) => upNum("runtime", v)} type="number" />
        <Inp label="ramp_time (s)" value={job.ramp_time} onChange={(v) => upNum("ramp_time", v)} type="number" />
        <Inp label="startdelay (s)" value={job.startdelay} onChange={(v) => upNum("startdelay", v)} type="number" />
        <Inp label="loops" value={job.loops} onChange={(v) => upNum("loops", v)} type="number" />
        <Inp label="number_ios" value={job.number_ios} onChange={(v) => upNum("number_ios", v)} type="number" />
        <Toggle label="time_based" value={job.time_based} onChange={(v) => onChange({ ...job, time_based: v })} />
      </Section>

      <Section title="I/O Engine">
        <Sel label="ioengine" value={job.ioengine} options={["", ...IOENGINES]} onChange={(v) => up("ioengine", v)} />
        <Inp label="iodepth_batch" value={job.iodepth_batch} onChange={(v) => upNum("iodepth_batch", v)} type="number" />
        <Inp label="iodepth_batch_complete_min" value={job.iodepth_batch_complete_min} onChange={(v) => upNum("iodepth_batch_complete_min", v)} type="number" />
        <Inp label="iodepth_batch_complete_max" value={job.iodepth_batch_complete_max} onChange={(v) => upNum("iodepth_batch_complete_max", v)} type="number" />
        <Toggle label="sqthread_poll (io_uring)" value={job.sqthread_poll} onChange={(v) => onChange({ ...job, sqthread_poll: v })} />
        <Inp label="sqthread_poll_cpu" value={job.sqthread_poll_cpu} onChange={(v) => upNum("sqthread_poll_cpu", v)} type="number" />
      </Section>

      <Section title="Buffering &amp; Sync">
        <Toggle label="direct" value={job.direct} onChange={(v) => onChange({ ...job, direct: v })} />
        <Toggle label="buffered" value={job.buffered} onChange={(v) => onChange({ ...job, buffered: v })} />
        <Toggle label="invalidate" value={job.invalidate} onChange={(v) => onChange({ ...job, invalidate: v })} />
        <Inp label="fsync (every N writes)" value={job.fsync} onChange={(v) => upNum("fsync", v)} type="number" />
        <Inp label="fdatasync (every N writes)" value={job.fdatasync} onChange={(v) => upNum("fdatasync", v)} type="number" />
        <Toggle label="fsync_on_close" value={job.fsync_on_close} onChange={(v) => onChange({ ...job, fsync_on_close: v })} />
      </Section>

      <Section title="Rate Limiting">
        <Inp label="rate (BW limit)" value={job.rate} onChange={(v) => up("rate", v)} placeholder="100m" />
        <Inp label="rate_iops" value={job.rate_iops} onChange={(v) => upNum("rate_iops", v)} type="number" />
        <Inp label="rate_min" value={job.rate_min} onChange={(v) => up("rate_min", v)} placeholder="10m" />
        <Sel label="rate_process" value={job.rate_process} options={RATE_PROC} onChange={(v) => up("rate_process", v)} />
      </Section>

      <Section title="Offset &amp; Distribution">
        <Inp label="offset" value={job.offset} onChange={(v) => up("offset", v)} placeholder="0" />
        <Inp label="offset_increment" value={job.offset_increment} onChange={(v) => up("offset_increment", v)} placeholder="100g" />
        <Sel label="random_distribution" value={job.random_distribution} options={RAND_DIST} onChange={(v) => up("random_distribution", v)} />
        <Sel label="random_generator" value={job.random_generator} options={RAND_GEN} onChange={(v) => up("random_generator", v)} />
        <Toggle label="norandommap" value={job.norandommap} onChange={(v) => onChange({ ...job, norandommap: v })} />
        <Toggle label="randrepeat" value={job.randrepeat} onChange={(v) => onChange({ ...job, randrepeat: v })} />
      </Section>

      <Section title="CPU &amp; Priority">
        <Inp label="cpus_allowed" value={job.cpus_allowed} onChange={(v) => up("cpus_allowed", v)} placeholder="0-3" />
        <Sel label="cpus_allowed_policy" value={job.cpus_allowed_policy} options={CPU_POLICY} onChange={(v) => up("cpus_allowed_policy", v)} />
        <Inp label="nice" value={job.nice} onChange={(v) => upNum("nice", v)} type="number" />
        <Inp label="prio" value={job.prio} onChange={(v) => upNum("prio", v)} type="number" />
        <Sel label="prioclass (1=RT,2=BE,3=IDLE)" value={job.prioclass?.toString()} options={IO_PRIO_CLASS} onChange={(v) => upNum("prioclass", v)} />
      </Section>

      <Section title="Verification">
        <Sel label="verify" value={job.verify} options={VERIFY_OPTIONS} onChange={(v) => up("verify", v)} />
        <Inp label="verify_pattern" value={job.verify_pattern} onChange={(v) => up("verify_pattern", v)} placeholder="0xdeadbeef" />
        <Toggle label="verify_fatal" value={job.verify_fatal} onChange={(v) => onChange({ ...job, verify_fatal: v })} />
        <Toggle label="do_verify (separate verify pass)" value={job.do_verify} onChange={(v) => onChange({ ...job, do_verify: v })} />
      </Section>

      <Section title="Job Control">
        <Toggle label="exitall (stop all when done)" value={job.exitall} onChange={(v) => onChange({ ...job, exitall: v })} />
        <Toggle label="new_group" value={job.new_group} onChange={(v) => onChange({ ...job, new_group: v })} />
      </Section>
    </div>
  );
}

// ─────────────────────── Global options editor ────────────────────────────

function GlobalOptsEditor({
  opts, onChange,
}: {
  opts: FioStepConfig["global_options"]; onChange: (o: FioStepConfig["global_options"]) => void;
}) {
  function up(key: string, val: any) {
    onChange({ ...opts, [key]: val === "" ? undefined : val });
  }
  function upNum(key: string, val: string) {
    onChange({ ...opts, [key]: val === "" ? undefined : Number(val) });
  }

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">[global] Section</p>
      <div className="grid grid-cols-2 gap-2">
        <Sel label="ioengine" value={opts.ioengine} options={IOENGINES} onChange={(v) => up("ioengine", v)} />
        <Toggle label="direct" value={opts.direct} onChange={(v) => onChange({ ...opts, direct: v ?? 0 })} />
        <Inp label="runtime (s)" value={opts.runtime} onChange={(v) => upNum("runtime", v)} type="number" />
        <Inp label="ramp_time (s)" value={opts.ramp_time} onChange={(v) => upNum("ramp_time", v)} type="number" />
        <Inp label="numjobs" value={opts.numjobs} onChange={(v) => upNum("numjobs", v)} type="number" />
        <Inp label="log_avg_msec" value={opts.log_avg_msec} onChange={(v) => upNum("log_avg_msec", v)} type="number" />
        <Inp label="filename" value={opts.filename} onChange={(v) => up("filename", v)} placeholder="/dev/sda" className="col-span-2" />
        <Inp label="directory" value={opts.directory} onChange={(v) => up("directory", v)} placeholder="/mnt/test" className="col-span-2" />
        <Inp label="size" value={opts.size} onChange={(v) => up("size", v)} placeholder="1g" />
        <Toggle label="time_based" value={opts.time_based} onChange={(v) => onChange({ ...opts, time_based: v ?? 0 })} />
        <Toggle label="group_reporting" value={opts.group_reporting} onChange={(v) => onChange({ ...opts, group_reporting: v ?? 0 })} />
        <Toggle label="thread" value={opts.thread} onChange={(v) => onChange({ ...opts, thread: v ?? 0 })} />
      </div>
    </div>
  );
}

// ─────────────────────── Main FioConfig panel ─────────────────────────────

export default function FioConfig() {
  const { activeFlow, setActiveFlow, selectedStepId } = useStore();

  const step = activeFlow?.steps.find((s) => s.id === selectedStepId);
  if (!step || step.type !== "fio") {
    return <div className="p-4 text-sm text-gray-400">Select a FIO test node to configure it.</div>;
  }

  const cfg = step.config as FioStepConfig;

  function updateStep(newCfg: FioStepConfig) {
    if (!activeFlow) return;
    setActiveFlow({
      ...activeFlow,
      steps: activeFlow.steps.map((s) =>
        s.id === step.id ? { ...s, config: newCfg } : s,
      ),
    });
  }

  function updateName(name: string) {
    if (!activeFlow) return;
    setActiveFlow({
      ...activeFlow,
      steps: activeFlow.steps.map((s) =>
        s.id === step.id ? { ...s, name } : s,
      ),
    });
  }

  function addJob() {
    updateStep({
      ...cfg,
      jobs: [
        ...cfg.jobs,
        { name: `job${cfg.jobs.length + 1}`, rw: "randread", bs: "4k", iodepth: 32 },
      ],
    });
  }

  function removeJob(i: number) {
    updateStep({ ...cfg, jobs: cfg.jobs.filter((_, idx) => idx !== i) });
  }

  function updateJob(i: number, job: FioJob) {
    updateStep({ ...cfg, jobs: cfg.jobs.map((j, idx) => (idx === i ? job : j)) });
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-blue-50">
        <input
          value={step.name}
          onChange={(e) => updateName(e.target.value)}
          className="text-sm font-semibold bg-transparent border-b border-blue-200 focus:outline-none focus:border-blue-500 w-full"
        />
        <p className="text-xs text-blue-600 mt-0.5">FIO Test Configuration</p>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        <GlobalOptsEditor
          opts={cfg.global_options}
          onChange={(o) => updateStep({ ...cfg, global_options: o })}
        />

        <hr className="border-gray-100" />

        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Jobs ({cfg.jobs.length})
          </p>
          <button
            onClick={addJob}
            className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 font-medium"
          >
            <Plus size={12} /> Add Job
          </button>
        </div>

        {cfg.jobs.map((job, i) => (
          <JobEditor
            key={i}
            job={job}
            onChange={(j) => updateJob(i, j)}
            onRemove={() => removeJob(i)}
            showRemove={cfg.jobs.length > 1}
          />
        ))}
      </div>
    </div>
  );
}
