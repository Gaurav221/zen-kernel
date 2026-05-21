"""Export a Flow to standalone Bash and Python scripts + .fio job files."""
from __future__ import annotations
import json
import os
import re
import textwrap
from pathlib import Path
from typing import Dict, List, Tuple

from .models import (
    CommandStepConfig, FioStepConfig, Flow, FlowStep,
    LogCollectStepConfig,
)
from .fio_config import render_fio_file
from .executor import topological_order


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)


# ──────────────────────────── .fio file writing ───────────────────────────

def _fio_files(steps: List[FlowStep], out_dir: str) -> Dict[str, str]:
    """Return {step_id: relative_path_to_fio_file}."""
    result = {}
    for i, step in enumerate(steps):
        if step.type != "fio":
            continue
        safe = _safe(step.name)
        rel_log = f"$OUTPUT_DIR/{i:03d}_fio_{safe}"
        fio_content = render_fio_file(step.config, rel_log, step.name)
        rel_path = f"jobs/{i:03d}_{safe}.fio"
        result[step.id] = (rel_path, fio_content)
    return result


# ───────────────────────────── Bash exporter ──────────────────────────────

def export_bash(flow: Flow, out_dir: str) -> List[Tuple[str, str]]:
    """
    Return list of (relative_path, content) to write.
    Produces:
      run.sh
      jobs/NNN_name.fio   (one per FIO step)
    """
    files: List[Tuple[str, str]] = []
    steps = flow.steps
    edges = flow.edges
    waves = topological_order(steps, edges)
    step_map = {s.id: s for s in steps}

    fio_map: Dict[str, Tuple[str, str]] = {}
    for i, step in enumerate(steps):
        if step.type != "fio":
            continue
        safe = _safe(step.name)
        log_placeholder = '"${OUTPUT_DIR}/' + f'{i:03d}_fio_{safe}"'
        fio_content = render_fio_file(step.config, f"__LOG_DIR_{i}__", step.name)
        fio_content = fio_content.replace(f"__LOG_DIR_{i}__", f"${{OUTPUT_DIR}}/{i:03d}_fio_{safe}")
        rel_path = f"jobs/{i:03d}_{safe}.fio"
        fio_map[step.id] = (rel_path, fio_content)
        files.append((rel_path, fio_content))

    # Build run.sh
    header = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # FIO Orchestrator — generated script
        # Flow: {flow.name}
        # {flow.description}
        set -euo pipefail

        SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
        OUTPUT_DIR="${{1:-{flow.output_dir}/$(date +%Y%m%d_%H%M%S)}}"
        mkdir -p "$OUTPUT_DIR"

        log() {{ echo "[$(date +%H:%M:%S)] $*" | tee -a "$OUTPUT_DIR/run.log"; }}
        die() {{ log "ERROR: $*"; exit 1; }}

        log "Run output: $OUTPUT_DIR"
        log "Flow: {flow.name}"

    """)

    body_lines: List[str] = []
    global_idx = 0

    for wave in waves:
        if len(wave) > 1:
            body_lines.append("# ── Parallel wave ──────────────────────────────")
            body_lines.append("pids=()")

        for sid in wave:
            step = step_map[sid]
            safe = _safe(step.name)
            step_dir = f'"${{OUTPUT_DIR}}/{global_idx:03d}_{step.type}_{safe}"'
            body_lines.append(f'\nlog "Step: {step.name}"')
            body_lines.append(f'mkdir -p {step_dir}')

            if step.type == "fio":
                fio_path, _ = fio_map[step.id]
                json_out = f'{step_dir}/fio_output.json'
                txt_out  = f'{step_dir}/fio_output.txt'
                cmd = (f'fio "${{SCRIPT_DIR}}/{fio_path}" '
                       f'--output={json_out} --output-format=json '
                       f'2>&1 | tee {txt_out}')
                if len(wave) > 1:
                    body_lines.append(f'( {cmd} ) &')
                    body_lines.append('pids+=($!)')
                else:
                    body_lines.append(cmd)

            elif step.type == "log_collect":
                cfg: LogCollectStepConfig = step.config
                for ci, collector in enumerate(cfg.collectors):
                    t = collector.type
                    if t == "iostat":
                        devs = " ".join(collector.devices) if collector.devices else ""
                        count = str(collector.count) if collector.count else ""
                        cmd = (f'iostat -xdt {collector.interval} {devs} {count} '
                               f'> {step_dir}/iostat.log 2>&1')
                    elif t == "blktrace":
                        devs = " ".join(f"-d {d}" for d in collector.devices)
                        cmd = (f'blktrace {devs} -o {step_dir}/blktrace_{ci} '
                               f'> {step_dir}/blktrace_{ci}.log 2>&1')
                    elif t == "perf_stat":
                        evts = ",".join(collector.events)
                        cmd = (f'perf stat -e {evts} sleep {collector.duration or 60} '
                               f'> {step_dir}/perf_stat_{ci}.log 2>&1')
                    elif t == "perf_record":
                        evts = ",".join(collector.events)
                        out = f'{step_dir}/perf_{ci}.data'
                        cmd = (f'perf record -e {evts} -F {collector.frequency} -a '
                               f'-o {out} sleep {collector.duration or 60} '
                               f'> {step_dir}/perf_record_{ci}.log 2>&1')
                    elif t == "dmesg":
                        cmd = f'dmesg --time-format=iso > {step_dir}/dmesg_{ci}.log 2>&1'
                    elif t == "custom":
                        safe_lbl = _safe(collector.label)
                        cmd = (f'bash -c {json.dumps(collector.command)} '
                               f'> {step_dir}/cmd_{ci}_{safe_lbl}.log 2>&1')
                    else:
                        continue

                    if len(wave) > 1 or cfg.duration:
                        body_lines.append(f'( {cmd} ) &')
                        body_lines.append('pids+=($!)')
                    else:
                        body_lines.append(cmd)

            elif step.type == "command":
                cfg: CommandStepConfig = step.config
                safe_lbl = _safe(cfg.label)
                cmd = (f'bash -c {json.dumps(cfg.command)} '
                       f'> {step_dir}/{safe_lbl}.log 2>&1')
                if len(wave) > 1:
                    body_lines.append(f'( {cmd} ) &')
                    body_lines.append('pids+=($!)')
                else:
                    body_lines.append(cmd)

            global_idx += 1

        if len(wave) > 1:
            body_lines.append('\n# Wait for parallel steps')
            body_lines.append('for pid in "${pids[@]}"; do wait "$pid" || die "step failed (pid $pid)"; done')
            body_lines.append('pids=()')

    footer = textwrap.dedent("""
        log "All steps complete."
        log "Results in: $OUTPUT_DIR"
    """)

    run_sh = header + "\n".join(body_lines) + footer
    files.insert(0, ("run.sh", run_sh))
    return files


# ──────────────────────────── Python exporter ─────────────────────────────

def export_python(flow: Flow, out_dir: str) -> List[Tuple[str, str]]:
    """
    Return list of (relative_path, content) to write.
    Produces:
      run.py
      jobs/NNN_name.fio
    """
    files: List[Tuple[str, str]] = []
    steps = flow.steps
    edges = flow.edges
    waves = topological_order(steps, edges)
    step_map = {s.id: s for s in steps}

    fio_map: Dict[str, Tuple[str, str]] = {}
    for i, step in enumerate(steps):
        if step.type != "fio":
            continue
        safe = _safe(step.name)
        fio_content = render_fio_file(step.config, f"__LOG_DIR_{i}__", step.name)
        fio_content = fio_content.replace(
            f"__LOG_DIR_{i}__", f"{{log_dir}}")
        rel_path = f"jobs/{i:03d}_{safe}.fio"
        fio_map[step.id] = (i, safe, rel_path, fio_content)
        files.append((rel_path, fio_content.replace("{log_dir}", f"./results")))

    wave_code: List[str] = []
    global_idx = 0

    for wave in waves:
        for sid in wave:
            step = step_map[sid]
            safe = _safe(step.name)
            idx = global_idx
            step_dir_expr = f'os.path.join(output_dir, f"{idx:03d}_{step.type}_{safe}")'

            wave_code.append(f'\n    # Step: {step.name}')
            wave_code.append(f'    log_dir = {step_dir_expr}')
            wave_code.append(f'    os.makedirs(log_dir, exist_ok=True)')
            wave_code.append(f'    step_meta = {{"name": {json.dumps(step.name)}, "type": {json.dumps(step.type)}, "started": str(datetime.utcnow())}}')

            if step.type == "fio":
                i_fio, safe_fio, rel_path, _ = fio_map[step.id]
                wave_code.append(f'    fio_file = os.path.join(SCRIPT_DIR, {json.dumps(rel_path)})')
                wave_code.append(f'    # rewrite log paths in .fio to point to log_dir')
                wave_code.append(f'    fio_content = open(fio_file).read().replace("./results", log_dir)')
                wave_code.append(f'    tmp_fio = os.path.join(log_dir, "job.fio")')
                wave_code.append(f'    open(tmp_fio, "w").write(fio_content)')
                wave_code.append(f'    json_out = os.path.join(log_dir, "fio_output.json")')
                wave_code.append(f'    txt_out  = os.path.join(log_dir, "fio_output.txt")')
                wave_code.append(f'    run_cmd(["fio", tmp_fio, f"--output={{json_out}}", "--output-format=json"], txt_out, step_meta)')

            elif step.type == "log_collect":
                cfg: LogCollectStepConfig = step.config
                for ci, col in enumerate(cfg.collectors):
                    t = col.type
                    if t == "iostat":
                        devs = col.devices if col.devices else []
                        cnt = col.count or ""
                        wave_code.append(
                            f'    run_cmd(["iostat", "-xdt", "{col.interval}"] + {devs!r} + (["{cnt}"] if "{cnt}" else []),'
                            f' os.path.join(log_dir, "iostat.log"), step_meta)')
                    elif t == "dmesg":
                        wave_code.append(
                            f'    run_cmd(["dmesg", "--time-format=iso"],'
                            f' os.path.join(log_dir, f"dmesg_{ci}.log"), step_meta)')
                    elif t == "custom":
                        safe_lbl = _safe(col.label)
                        wave_code.append(
                            f'    run_cmd(["bash", "-c", {json.dumps(col.command)}],'
                            f' os.path.join(log_dir, f"cmd_{ci}_{safe_lbl}.log"), step_meta)')

            elif step.type == "command":
                cfg: CommandStepConfig = step.config
                safe_lbl = _safe(cfg.label)
                wave_code.append(
                    f'    run_cmd(["bash", "-c", {json.dumps(cfg.command)}],'
                    f' os.path.join(log_dir, "{safe_lbl}.log"), step_meta)')

            wave_code.append(f'    step_meta["finished"] = str(datetime.utcnow())')
            wave_code.append(f'    save_json(step_meta, os.path.join(log_dir, "metadata.json"))')
            global_idx += 1

    py = textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"FIO Orchestrator — generated Python runner
        Flow: {flow.name}
        {flow.description}
        \"\"\"
        import json
        import os
        import subprocess
        import sys
        from datetime import datetime
        from pathlib import Path

        SCRIPT_DIR = Path(__file__).parent.resolve()


        def log(msg):
            print(f"[{{datetime.now().strftime('%H:%M:%S')}}] {{msg}}", flush=True)


        def save_json(data, path):
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)


        def run_cmd(cmd, log_path, meta):
            log(f"RUN: {{' '.join(str(c) for c in cmd)}}")
            with open(log_path, "wb") as fout:
                result = subprocess.run(cmd, stdout=fout, stderr=subprocess.STDOUT)
            meta.setdefault("commands", []).append({{"cmd": cmd, "rc": result.returncode}})
            if result.returncode != 0:
                log(f"WARNING: exit code {{result.returncode}}")
            return result.returncode


        def main():
            output_dir = sys.argv[1] if len(sys.argv) > 1 else \\
                os.path.join("{flow.output_dir}", datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(output_dir, exist_ok=True)
            run_meta = {{
                "flow": {json.dumps(flow.name)},
                "description": {json.dumps(flow.description)},
                "output_dir": output_dir,
                "started": str(datetime.utcnow()),
            }}
            log(f"Flow: {flow.name}")
            log(f"Output: {{output_dir}}")
        {''.join(wave_code)}

            run_meta["finished"] = str(datetime.utcnow())
            save_json(run_meta, os.path.join(output_dir, "run_metadata.json"))
            log("Done.")


        if __name__ == "__main__":
            main()
    """)

    files.insert(0, ("run.py", py))
    return files


# ──────────────────────────── Unified export ──────────────────────────────

def export_flow(flow: Flow, fmt: str, base_dir: str) -> List[Tuple[str, str]]:
    """Return all (rel_path, content) pairs for the requested format."""
    if fmt == "bash":
        return export_bash(flow, base_dir)
    if fmt == "python":
        return export_python(flow, base_dir)
    # both
    bash_files = export_bash(flow, base_dir)
    py_files = export_python(flow, base_dir)
    # Merge — .fio files appear in both; deduplicate by path
    seen = set()
    merged = []
    for path, content in bash_files + py_files:
        if path not in seen:
            seen.add(path)
            merged.append((path, content))
    return merged
