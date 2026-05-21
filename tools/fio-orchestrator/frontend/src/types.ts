// ─────────────────────── FIO Parameter types ──────────────────────────────

export interface FioGlobalOptions {
  ioengine: string;
  direct: number;
  group_reporting: number;
  time_based: number;
  runtime: number;
  ramp_time: number;
  filename?: string;
  directory?: string;
  size?: string;
  numjobs: number;
  thread: number;
  log_avg_msec: number;
  [key: string]: unknown;
}

export interface FioJob {
  name: string;
  description?: string;
  // Workload
  rw: string;
  rwmixread?: number;
  rwmixwrite?: number;
  bs: string;
  bsrange?: string;
  bssplit?: string;
  iodepth: number;
  iodepth_batch?: number;
  iodepth_batch_complete_min?: number;
  iodepth_batch_complete_max?: number;
  numjobs?: number;
  // Target
  filename?: string;
  directory?: string;
  size?: string;
  fill_device?: number;
  filesize?: string;
  io_size?: string;
  nrfiles?: number;
  openfiles?: number;
  // Timing
  runtime?: number;
  time_based?: number;
  ramp_time?: number;
  startdelay?: number;
  loops?: number;
  number_ios?: number;
  // Buffering
  direct?: number;
  buffered?: number;
  invalidate?: number;
  // Sync
  fsync?: number;
  fdatasync?: number;
  fsync_on_close?: number;
  // Rate
  rate?: string;
  rate_iops?: number;
  rate_min?: string;
  rate_process?: string;
  // Offset
  offset?: string;
  offset_increment?: string;
  random_distribution?: string;
  // CPU/priority
  cpus_allowed?: string;
  cpus_allowed_policy?: string;
  nice?: number;
  prio?: number;
  prioclass?: number;
  // Memory
  mem?: string;
  lockmem?: string;
  // Random
  norandommap?: number;
  randrepeat?: number;
  random_generator?: string;
  // Verify
  verify?: string;
  verify_pattern?: string;
  verify_fatal?: number;
  do_verify?: number;
  // Logs
  write_bw_log?: string;
  write_iops_log?: string;
  write_lat_log?: string;
  write_hist_log?: string;
  per_job_logs?: number;
  // Job control
  stonewall?: number;
  new_group?: number;
  exitall?: number;
  // Engine specific
  ioengine?: string;
  sqthread_poll?: number;
  [key: string]: unknown;
}

export interface FioStepConfig {
  global_options: FioGlobalOptions;
  jobs: FioJob[];
}

// ─────────────────────── Collector types ──────────────────────────────────

export interface IostatCollector {
  type: "iostat";
  devices: string[];
  interval: number;
  count?: number;
}

export interface BlktraceCollector {
  type: "blktrace";
  devices: string[];
  duration?: number;
}

export interface PerfStatCollector {
  type: "perf_stat";
  events: string[];
  pid?: number;
  cpu?: string;
  duration?: number;
}

export interface PerfRecordCollector {
  type: "perf_record";
  events: string[];
  frequency: number;
  pid?: number;
  cpu?: string;
  duration?: number;
}

export interface DmesgCollector {
  type: "dmesg";
  clear_before: boolean;
}

export interface CustomCollector {
  type: "custom";
  command: string;
  label: string;
  timeout?: number;
  working_dir?: string;
  env: Record<string, string>;
}

export type CollectorConfig =
  | IostatCollector
  | BlktraceCollector
  | PerfStatCollector
  | PerfRecordCollector
  | DmesgCollector
  | CustomCollector;

export interface LogCollectStepConfig {
  collectors: CollectorConfig[];
  duration?: number;
}

// ─────────────────────── Command step ─────────────────────────────────────

export interface CommandStepConfig {
  command: string;
  label: string;
  timeout?: number;
  working_dir?: string;
  env: Record<string, string>;
  fail_on_error: boolean;
}

// ─────────────────────────── Flow ─────────────────────────────────────────

export type StepType = "fio" | "log_collect" | "command";

export interface FlowStep {
  id: string;
  type: StepType;
  name: string;
  config: FioStepConfig | LogCollectStepConfig | CommandStepConfig;
  position_x: number;
  position_y: number;
}

export interface FlowEdge {
  id: string;
  source: string;
  target: string;
}

export interface Flow {
  id: string;
  name: string;
  description: string;
  steps: FlowStep[];
  edges: FlowEdge[];
  output_dir: string;
  created_at: string;
  updated_at: string;
}

// ─────────────────────────── Runs ─────────────────────────────────────────

export interface StepStatus {
  step_id: string;
  step_name: string;
  status: "pending" | "running" | "done" | "error" | "skipped";
  started_at?: string;
  finished_at?: string;
  exit_code?: number;
  log_dir?: string;
  error?: string;
}

export interface RunRecord {
  id: string;
  flow_id: string;
  flow_name: string;
  status: "pending" | "running" | "done" | "error" | "cancelled";
  started_at: string;
  finished_at?: string;
  output_dir: string;
  steps: StepStatus[];
}

// ─────────────────────────── Templates ────────────────────────────────────

export interface Template {
  id: string;
  name: string;
  category: string;
  description: string;
  config: FioStepConfig;
}

// ─────────────────────────── Analysis ─────────────────────────────────────

export interface FioJobSummary {
  job_name: string;
  error: number;
  read?: FioDirectionStats;
  write?: FioDirectionStats;
}

export interface FioDirectionStats {
  io_bytes: number;
  bw_mbps: number;
  iops: number;
  lat_mean_us: number;
  clat_p50_us: number;
  clat_p99_us: number;
  clat_p999_us: number;
}

export interface TimeseriesPoint {
  time_ms: number;
  value: number;
  dir: number;
  bs: number;
}

export interface StepSummary {
  log_dir: string;
  fio_jobs?: FioJobSummary[];
  timeseries?: Record<string, TimeseriesPoint[]>;
  iostat?: Record<string, string>[];
}

// ─────────────────────────── WS Messages ──────────────────────────────────

export interface WsMessage {
  type: "log" | "step_start" | "step_done" | "run_done" | "error";
  step_id?: string;
  step_name?: string;
  data?: unknown;
  ts: string;
}
