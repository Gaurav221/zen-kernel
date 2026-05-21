"""
Generates text, rich-terminal, and HTML reports from parsed FIO analyses.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .workflow import Workflow


# ---------------------------------------------------------------------------
# Terminal (rich) report
# ---------------------------------------------------------------------------

def print_fio_summary_table(analyses: List[Dict], console: Optional[Console] = None) -> None:
    """Print a rich comparison table for all FIO steps."""
    if not console:
        console = Console()
    if not analyses:
        console.print("[yellow]No FIO results to display.[/]")
        return

    table = Table(
        title="FIO Results Summary",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        highlight=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Step", style="bold white", min_width=20)
    table.add_column("rw", style="cyan", width=12)
    table.add_column("bs", width=6)
    table.add_column("Read IOPS", justify="right", style="green")
    table.add_column("Write IOPS", justify="right", style="yellow")
    table.add_column("Read BW", justify="right", style="green")
    table.add_column("Write BW", justify="right", style="yellow")
    table.add_column("p99 R lat", justify="right", style="magenta")
    table.add_column("p99 W lat", justify="right", style="magenta")

    for a in analyses:
        s = a.get("summary", {})
        opts = {}
        for job in a.get("jobs", []):
            opts = job.get("job_options", {})
            break

        rw = opts.get("rw", "?")
        bs = opts.get("bs", "?")

        def fmt_iops(v):
            if not v:
                return "─"
            if v >= 1_000_000:
                return f"{v/1_000_000:.1f}M"
            if v >= 1000:
                return f"{v/1000:.1f}k"
            return f"{v:.0f}"

        def fmt_bw(mib):
            if not mib:
                return "─"
            if mib >= 1024:
                return f"{mib/1024:.1f} GiB/s"
            return f"{mib:.1f} MiB/s"

        def fmt_lat(us):
            if us is None:
                return "─"
            if us >= 1000:
                return f"{us/1000:.1f}ms"
            return f"{us:.0f}µs"

        table.add_row(
            str(a.get("step_index", "")),
            a.get("step_name", "?"),
            rw,
            str(bs),
            fmt_iops(s.get("total_read_iops")),
            fmt_iops(s.get("total_write_iops")),
            fmt_bw(s.get("total_read_bw_MiB_s")),
            fmt_bw(s.get("total_write_bw_MiB_s")),
            fmt_lat(s.get("p99_read_lat_us")),
            fmt_lat(s.get("p99_write_lat_us")),
        )

    console.print(table)


def print_detailed_analysis(analysis: Dict, console: Optional[Console] = None) -> None:
    """Print detailed per-step analysis."""
    if not console:
        console = Console()

    step_name = analysis.get("step_name", "unknown")
    console.print(Panel(f"[bold]{step_name}[/bold]  •  {analysis.get('fio_version', '')}",
                        style="cyan"))

    for job in analysis.get("jobs", []):
        for direction in ("read", "write"):
            d = job.get(direction)
            if not d:
                continue

            tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            tbl.add_column("Metric", style="dim")
            tbl.add_column("Value", style="bold")

            tbl.add_row("IOPS", f"{d['iops']:,.0f}  (min={d['iops_min']:,}  max={d['iops_max']:,})")
            bw = d['bw_MiB_s']
            tbl.add_row("Bandwidth", f"{bw:.2f} MiB/s  ({bw/1024:.2f} GiB/s)")

            lat = d.get("lat_ns", {})
            if lat:
                tbl.add_row("Lat mean", f"{lat['mean']/1000:.1f} µs")
                tbl.add_row("Lat min/max", f"{lat['min']/1000:.1f} / {lat['max']/1000:.1f} µs")

            pctiles = d.get("clat_percentiles_us", {})
            if pctiles:
                pline = "  ".join(f"p{k.lstrip('p')}={v}µs" for k, v in sorted(pctiles.items()))
                tbl.add_row("Percentiles", pline)

            console.print(Panel(tbl, title=f"[bold]{direction.upper()}[/bold]"))


# ---------------------------------------------------------------------------
# Text report (no rich, suitable for log files)
# ---------------------------------------------------------------------------

def build_text_report(analyses: List[Dict]) -> str:
    lines = [
        "=" * 72,
        "  FIO BENCHMARK SUMMARY",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 72,
        "",
    ]

    for a in analyses:
        s = a.get("summary", {})
        step_name = a.get("step_name", "?")
        step_idx  = a.get("step_index", 0)
        opts = {}
        for job in a.get("jobs", []):
            opts = job.get("job_options", {})
            break

        lines.append(f"[{step_idx:03d}] {step_name}")
        lines.append(f"      rw={opts.get('rw','?')}  bs={opts.get('bs','?')}  "
                     f"iodepth={opts.get('iodepth','?')}  numjobs={opts.get('numjobs','?')}")

        def lat_str(v):
            if v is None: return "N/A"
            return f"{v/1000:.2f}ms" if v >= 1000 else f"{v:.0f}us"

        if s.get("total_read_iops"):
            lines.append(f"      READ:  iops={s['total_read_iops']:.0f}  "
                         f"bw={s['total_read_bw_MiB_s']:.1f} MiB/s  "
                         f"p99_lat={lat_str(s.get('p99_read_lat_us'))}")
        if s.get("total_write_iops"):
            lines.append(f"      WRITE: iops={s['total_write_iops']:.0f}  "
                         f"bw={s['total_write_bw_MiB_s']:.1f} MiB/s  "
                         f"p99_lat={lat_str(s.get('p99_write_lat_us'))}")

        for job in a.get("jobs", []):
            for direction in ("read", "write"):
                d = job.get(direction)
                if not d:
                    continue
                pct = d.get("clat_percentiles_us", {})
                if pct:
                    pline = "  ".join(f"{k}={v}us" for k, v in sorted(pct.items()))
                    lines.append(f"      {direction.upper()} percentiles: {pline}")
        lines.append("")

    lines.append("=" * 72)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON summary (machine-readable comparison)
# ---------------------------------------------------------------------------

def build_summary_json(analyses: List[Dict]) -> Dict:
    return {
        "generated": datetime.now().isoformat(),
        "steps": [
            {
                "step_index": a.get("step_index"),
                "step_name":  a.get("step_name"),
                "fio_version": a.get("fio_version"),
                "timestamp":  a.get("timestamp"),
                "summary":    a.get("summary", {}),
                "job_options": next(
                    (j.get("job_options", {}) for j in a.get("jobs", [])), {}
                ),
            }
            for a in analyses
        ],
    }


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_HTML_STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; background:#0f0f0f; color:#e0e0e0; margin:0; }
h1,h2,h3 { color:#7dd3fc; }
.container { max-width:1200px; margin:0 auto; padding:2rem; }
.meta { background:#1a1a2e; border-left:4px solid #7dd3fc; padding:.8rem 1.2rem; margin-bottom:2rem; }
table { border-collapse:collapse; width:100%; margin-bottom:2rem; font-size:.9em; }
th { background:#1e3a5f; color:#7dd3fc; padding:.5rem .8rem; text-align:left; border-bottom:2px solid #7dd3fc; }
td { padding:.4rem .8rem; border-bottom:1px solid #2a2a2a; }
tr:hover td { background:#1a1a1a; }
.good  { color:#4ade80; }
.warn  { color:#facc15; }
.step-card { background:#141414; border:1px solid #2a2a2a; border-radius:6px;
             padding:1rem 1.5rem; margin-bottom:1.5rem; }
.badge-fio { background:#1e3a5f; color:#7dd3fc; padding:2px 8px; border-radius:4px; font-size:.8em; }
.badge-cmd { background:#2a1a1a; color:#f97316; padding:2px 8px; border-radius:4px; font-size:.8em; }
.data-blob { display:none; }
pre { background:#0a0a0a; padding:1rem; border-radius:4px; overflow-x:auto; font-size:.85em; }
"""


def _fmt_iops(v) -> str:
    if not v:
        return "─"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v/1000:.1f}k"
    return f"{v:.0f}"


def _fmt_bw(mib) -> str:
    if not mib:
        return "─"
    if mib >= 1024:
        return f"{mib/1024:.2f} GiB/s"
    return f"{mib:.2f} MiB/s"


def _fmt_lat(us) -> str:
    if us is None:
        return "─"
    if us >= 1000:
        return f"{us/1000:.2f} ms"
    return f"{us:.0f} µs"


def build_html_report(workflow: Workflow, analyses: List[Dict]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Summary table rows
    rows_html = ""
    for a in analyses:
        s = a.get("summary", {})
        opts = {}
        for job in a.get("jobs", []):
            opts = job.get("job_options", {})
            break

        rows_html += f"""
        <tr>
          <td>{a.get('step_index','')}</td>
          <td><strong>{a.get('step_name','?')}</strong></td>
          <td>{opts.get('rw','?')}</td>
          <td>{opts.get('bs','?')}</td>
          <td>{opts.get('iodepth','?')}</td>
          <td class="good">{_fmt_iops(s.get('total_read_iops'))}</td>
          <td class="warn">{_fmt_iops(s.get('total_write_iops'))}</td>
          <td class="good">{_fmt_bw(s.get('total_read_bw_MiB_s'))}</td>
          <td class="warn">{_fmt_bw(s.get('total_write_bw_MiB_s'))}</td>
          <td>{_fmt_lat(s.get('p99_read_lat_us'))}</td>
          <td>{_fmt_lat(s.get('p99_write_lat_us'))}</td>
          <td>{_fmt_lat(s.get('p99_9_read_lat_us'))}</td>
          <td>{_fmt_lat(s.get('p99_9_write_lat_us'))}</td>
        </tr>"""

    # Per-step detail cards
    cards_html = ""
    for a in analyses:
        step_name = a.get("step_name", "?")
        fio_ver   = a.get("fio_version", "")
        ts        = a.get("timestamp", "")

        pct_rows = ""
        for job in a.get("jobs", []):
            for direction in ("read", "write"):
                d = job.get(direction)
                if not d:
                    continue
                pcts = d.get("clat_percentiles_us", {})
                pct_cells = "".join(
                    f"<td>{pcts.get(k, '─')} µs</td>"
                    for k in ("p50","p90","p95","p99","p99_5","p99_9","p99_99")
                )
                lat = d.get("lat_ns", {})
                pct_rows += f"""
                <tr>
                  <td><strong>{direction.upper()}</strong></td>
                  <td>{d['iops']:,.0f}</td>
                  <td>{d['bw_MiB_s']:.2f} MiB/s</td>
                  <td>{lat.get('mean',0)/1000:.1f} µs</td>
                  <td>{lat.get('min',0)/1000:.1f} µs</td>
                  <td>{lat.get('max',0)/1000:.1f} µs</td>
                  {pct_cells}
                </tr>"""

        cards_html += f"""
        <div class="step-card">
          <h3><span class="badge-fio">FIO</span>&nbsp;{step_name}</h3>
          <small>{fio_ver} &nbsp;|&nbsp; {ts}</small>
          <table>
            <tr>
              <th>Direction</th><th>IOPS</th><th>Bandwidth</th>
              <th>Lat mean</th><th>Lat min</th><th>Lat max</th>
              <th>p50</th><th>p90</th><th>p95</th><th>p99</th>
              <th>p99.5</th><th>p99.9</th><th>p99.99</th>
            </tr>
            {pct_rows}
          </table>
        </div>"""

    data_json = json.dumps({"workflow": workflow.to_dict(), "analyses": analyses}, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>FIO Report – {workflow.name}</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
<div class="container">
  <h1>FIO Benchmark Report</h1>
  <div class="meta">
    <strong>Workflow:</strong> {workflow.name}<br>
    <strong>Description:</strong> {workflow.description or '─'}<br>
    <strong>Generated:</strong> {now}
  </div>

  <h2>Summary Comparison</h2>
  <table>
    <tr>
      <th>#</th><th>Step</th><th>rw</th><th>bs</th><th>iodepth</th>
      <th>Read IOPS</th><th>Write IOPS</th>
      <th>Read BW</th><th>Write BW</th>
      <th>p99 R lat</th><th>p99 W lat</th>
      <th>p99.9 R lat</th><th>p99.9 W lat</th>
    </tr>
    {rows_html}
  </table>

  <h2>Per-Step Detail</h2>
  {cards_html}

  <!-- Machine-readable embedded data — parse with: grep -A999999 'id="json-data"' report.html | python3 -c "..." -->
  <script id="json-data" type="application/json" class="data-blob">
{data_json}
  </script>
</div>
</body>
</html>"""
