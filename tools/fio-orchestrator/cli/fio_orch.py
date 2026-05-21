#!/usr/bin/env python3
"""FIO Orchestrator CLI — run flows and export scripts without the GUI."""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

from backend.models import Flow, RunRecord, StepStatus
from backend.executor import execute_flow
from backend.exporter import export_flow
from backend.log_parser import build_step_summary

console = Console()


# ──────────────────────────── Helpers ─────────────────────────────────────

def load_flow(path: str) -> Flow:
    with open(path) as f:
        return Flow.model_validate_json(f.read())


def broadcast_to_console(msg):
    if msg.type == "log" and msg.data:
        console.print(f"  [dim]{msg.data}[/dim]")
    elif msg.type == "step_start":
        console.print(f"\n[bold cyan]→ {msg.step_name}[/bold cyan]")
    elif msg.type == "step_done":
        d = msg.data or {}
        status = d.get("status", "?")
        color = "green" if status == "done" else "red"
        console.print(f"  [{color}]✓ {msg.step_name} [{status}][/{color}]")
    elif msg.type == "run_done":
        console.print("\n[bold green]Run complete.[/bold green]")
    elif msg.type == "error":
        console.print(f"[red]ERROR: {msg.data}[/red]")


# ──────────────────────────── Commands ────────────────────────────────────

@click.group()
def cli():
    """FIO Orchestrator — manage and run FIO benchmark flows."""
    pass


@cli.command()
@click.argument("flow_file")
@click.option("--output-dir", "-o", default="./results",
              help="Directory for results (default: ./results/TIMESTAMP)")
@click.option("--quiet", "-q", is_flag=True, help="Suppress per-line output")
def run(flow_file: str, output_dir: str, quiet: bool):
    """Run a flow defined in a JSON flow file."""
    flow = load_flow(flow_file)

    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    if output_dir == "./results":
        output_dir = f"./results/{ts}"

    step_statuses = [
        StepStatus(step_id=s.id, step_name=s.name, status="pending")
        for s in flow.steps
    ]
    run_rec = RunRecord(
        flow_id=flow.id,
        flow_name=flow.name,
        status="running",
        output_dir=output_dir,
        steps=step_statuses,
    )

    console.print(f"\n[bold]Flow:[/bold] {flow.name}")
    console.print(f"[bold]Steps:[/bold] {len(flow.steps)}")
    console.print(f"[bold]Output:[/bold] {output_dir}\n")

    broadcaster = None if quiet else broadcast_to_console

    result = asyncio.run(execute_flow(run_rec, flow.steps, flow.edges, broadcaster))

    # Summary table
    table = Table(title="Run Results", show_header=True, header_style="bold")
    table.add_column("Step", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Log dir")

    for s in result.steps:
        dur = ""
        if s.started_at and s.finished_at:
            delta = (s.finished_at - s.started_at).total_seconds()
            dur = f"{delta:.1f}s"
        status_style = {"done": "green", "error": "red", "running": "blue"}.get(s.status, "dim")
        table.add_row(
            s.step_name,
            f"[{status_style}]{s.status}[/{status_style}]",
            dur,
            s.log_dir or "",
        )

    console.print(table)
    console.print(f"\n[bold]Status:[/bold] {result.status}")
    console.print(f"[bold]Results in:[/bold] {output_dir}")


@cli.command()
@click.argument("flow_file")
@click.option("--format", "-f", type=click.Choice(["bash", "python", "both"]),
              default="both", help="Script format")
@click.option("--output-dir", "-o", default="./fio_export",
              help="Directory to write exported scripts")
@click.option("--results-dir", default="./results",
              help="Results dir embedded in generated scripts")
def export(flow_file: str, format: str, output_dir: str, results_dir: str):
    """Export a flow to standalone Bash/Python scripts + .fio job files."""
    flow = load_flow(flow_file)
    files = export_flow(flow, format, results_dir)

    os.makedirs(output_dir, exist_ok=True)
    for rel_path, content in files:
        full_path = os.path.join(output_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        if rel_path.endswith(".sh") or rel_path.endswith(".py"):
            os.chmod(full_path, 0o755)
        console.print(f"  [green]✓[/green] {full_path}")

    console.print(f"\n[bold]Exported {len(files)} files to:[/bold] {output_dir}")


@cli.command()
@click.argument("flow_file")
def validate(flow_file: str):
    """Validate a flow JSON file and show a summary."""
    flow = load_flow(flow_file)
    console.print(f"\n[bold green]✓ Valid flow[/bold green]")
    console.print(f"  Name:  {flow.name}")
    console.print(f"  Steps: {len(flow.steps)}")
    console.print(f"  Edges: {len(flow.edges)}")
    for s in flow.steps:
        console.print(f"    [{s.type}] {s.name}")


@cli.command()
@click.argument("results_dir")
def analyze(results_dir: str):
    """Print a summary table for a completed run directory."""
    run_meta_path = os.path.join(results_dir, "run_metadata.json")
    if not os.path.exists(run_meta_path):
        console.print(f"[red]No run_metadata.json in {results_dir}[/red]")
        sys.exit(1)

    table = Table(title=f"Run Analysis — {results_dir}", show_header=True, header_style="bold")
    table.add_column("Step dir", style="cyan")
    table.add_column("Job")
    table.add_column("Dir")
    table.add_column("IOPS", justify="right")
    table.add_column("BW MB/s", justify="right")
    table.add_column("Lat mean µs", justify="right")
    table.add_column("p99 µs", justify="right")

    step_dirs = sorted(
        d for d in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, d)) and d != "run_metadata.json"
    )

    for step_dir in step_dirs:
        full = os.path.join(results_dir, step_dir)
        summary = build_step_summary(full)
        for job in summary.get("fio_jobs", []):
            for direction in ("read", "write"):
                d = job.get(direction)
                if not d:
                    continue
                table.add_row(
                    step_dir,
                    job["job_name"],
                    direction,
                    f"{d['iops']:.0f}",
                    f"{d['bw_mbps']:.1f}",
                    f"{d['lat_mean_us']:.1f}",
                    f"{d['clat_p99_us']:.1f}",
                )

    console.print(table)


@cli.command("list-templates")
def list_templates():
    """Show all built-in FIO templates."""
    from backend.fio_config import TEMPLATES
    table = Table(title="Built-in Templates", header_style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Category")
    table.add_column("Name")
    table.add_column("Description")
    for t in TEMPLATES:
        table.add_row(t["id"], t["category"], t["name"], t["description"])
    console.print(table)


@cli.command("init-flow")
@click.argument("name")
@click.option("--template", "-t", help="Start from a template ID (see list-templates)")
@click.option("--output", "-o", default=None, help="Output .json file path")
def init_flow(name: str, template: Optional[str], output: Optional[str]):
    """Create a new flow JSON file, optionally seeded from a template."""
    from backend.fio_config import TEMPLATES_BY_ID
    from backend.models import FlowStep, FioStepConfig
    import uuid

    flow = Flow(
        id=str(uuid.uuid4()),
        name=name,
        description="",
        steps=[],
        edges=[],
        output_dir="./results",
    )

    if template:
        tpl = TEMPLATES_BY_ID.get(template)
        if not tpl:
            console.print(f"[red]Template '{template}' not found. Run list-templates.[/red]")
            sys.exit(1)
        step = FlowStep(
            id=str(uuid.uuid4())[:8],
            type="fio",
            name=tpl["name"].replace(" ", "_").lower(),
            config=tpl["config"],
            position_x=0,
            position_y=100,
        )
        flow.steps.append(step)

    out = output or f"{name.replace(' ', '_').lower()}.json"
    with open(out, "w") as f:
        f.write(flow.model_dump_json(indent=2))

    console.print(f"[green]✓[/green] Created: {out}")
    if template:
        console.print(f"  Seeded with template: {template}")


if __name__ == "__main__":
    cli()
