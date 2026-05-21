#!/usr/bin/env python3
"""
fio_bench – FIO workflow builder, runner, and analyzer.

Usage:
  python fio_bench.py new              # interactive builder (GUI/TUI)
  python fio_bench.py edit wf.yaml     # edit existing workflow
  python fio_bench.py run  wf.yaml     # run workflow headlessly
  python fio_bench.py export wf.yaml   # generate standalone shell script
  python fio_bench.py analyze <dir>    # analyze existing results directory
  python fio_bench.py show wf.yaml     # print pipeline without running
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_workflow(path: str):
    from fio_bench.workflow import Workflow
    p = Path(path)
    if not p.exists():
        console.print(f"[red]File not found:[/red] {path}")
        sys.exit(1)
    return Workflow.from_yaml(p)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """fio_bench – build, run, and analyze FIO storage benchmarks."""


@cli.command("new")
@click.option("--save", "-s", default=None, help="Save workflow to this YAML file")
@click.option("--name", "-n", default=None, help="Workflow name (skip prompt)")
def cmd_new(save, name):
    """Create a new workflow interactively (TUI pipeline builder)."""
    from fio_bench.workflow import GlobalFIOConfig, Workflow
    from fio_bench.builder import run_builder

    if not name:
        console.print(Panel("[bold cyan]FIO Workflow Builder[/bold cyan]\n"
                            "Build a sequence of FIO tests and log-collection steps.",
                            border_style="cyan"))
        name = Prompt.ask("  Workflow name", default="my_storage_test")
        desc = Prompt.ask("  Description (optional)", default="")
        out_dir = Prompt.ask("  Results output directory", default="./fio_results")
    else:
        desc = ""
        out_dir = "./fio_results"

    workflow = Workflow(name=name, description=desc, output_dir=out_dir)
    save_path = Path(save) if save else None
    run_builder(workflow, save_path=save_path)


@cli.command("edit")
@click.argument("workflow_file")
@click.option("--save", "-s", default=None, help="Save to a different file")
def cmd_edit(workflow_file, save):
    """Open an existing workflow YAML in the TUI builder."""
    from fio_bench.builder import run_builder
    workflow = _load_workflow(workflow_file)
    save_path = Path(save) if save else Path(workflow_file)
    run_builder(workflow, save_path=save_path)


@cli.command("run")
@click.argument("workflow_file")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would run, don't execute")
@click.option("--output-dir", "-o", default=None, help="Override output directory")
def cmd_run(workflow_file, dry_run, output_dir):
    """Run a workflow YAML headlessly (no TUI required)."""
    from fio_bench.executor import WorkflowExecutor
    from fio_bench.reporter import print_fio_summary_table

    workflow = _load_workflow(workflow_file)
    if output_dir:
        workflow.output_dir = output_dir

    console.print(Panel(
        f"[bold]{workflow.name}[/bold]\n"
        f"{workflow.description or ''}\n"
        f"[dim]Steps: {len(workflow.enabled_steps())} enabled / {len(workflow.steps)} total[/dim]",
        title="Running Workflow",
        border_style="green",
    ))

    if dry_run:
        console.print("[yellow]DRY RUN – no actual I/O or commands will execute[/yellow]\n")

    executor = WorkflowExecutor(
        workflow,
        on_status=lambda msg: console.print(f"  {msg}"),
        dry_run=dry_run,
    )
    run_dir = executor.execute()

    if executor.fio_analyses:
        console.print()
        print_fio_summary_table(executor.fio_analyses, console)

    console.print(f"\n[bold green]Results saved to:[/bold green] {run_dir}")


@cli.command("export")
@click.argument("workflow_file")
@click.argument("output_dir")
def cmd_export(workflow_file, output_dir):
    """
    Export workflow as a standalone bash script + FIO job files.

    The exported directory can be copied anywhere and run without
    Python or fio_bench installed (only fio itself is required).
    """
    from fio_bench.generator import generate_standalone_script
    workflow = _load_workflow(workflow_file)
    script = generate_standalone_script(workflow, Path(output_dir))

    console.print(Panel(
        f"[green]Export complete![/green]\n\n"
        f"[bold]Directory:[/bold]  {output_dir}/\n"
        f"[bold]Script:[/bold]     {script}\n"
        f"[bold]FIO jobs:[/bold]   {output_dir}/fio_jobs/\n"
        f"[bold]Workflow:[/bold]   {output_dir}/workflow.yaml\n\n"
        f"[dim]Run with:  bash {script}[/dim]",
        title="Standalone Export",
        border_style="green",
    ))


@cli.command("show")
@click.argument("workflow_file")
def cmd_show(workflow_file):
    """Pretty-print the workflow pipeline without running anything."""
    from fio_bench.workflow import Workflow
    from rich.table import Table
    from rich import box

    workflow = _load_workflow(workflow_file)

    console.print(Panel(
        f"[bold cyan]{workflow.name}[/bold cyan]\n"
        f"[dim]{workflow.description}[/dim]",
        title="Workflow Pipeline",
        border_style="cyan",
    ))

    steps = workflow.steps
    for i, step in enumerate(steps):
        icon  = "◈" if step.type == "fio" else "⚙"
        color = "cyan" if step.type == "fio" else "yellow"
        state = "" if step.enabled else " [dim red][DISABLED][/dim red]"
        console.print(f"  [{color}]{icon} {step.type.upper():3}[/{color}]  "
                      f"[bold]#{i+1:02d} {step.name}[/bold]{state}")
        detail = step.one_liner()
        if detail:
            console.print(f"              [dim]{detail}[/dim]")
        if step.description:
            console.print(f"              [italic dim]{step.description}[/italic dim]")
        if i < len(steps) - 1:
            console.print("              [dim]│[/dim]")
            console.print("              [dim]▼[/dim]")

    console.print()
    console.print(f"[dim]Global FIO: filename={workflow.global_fio.filename}  "
                  f"size={workflow.global_fio.size}  "
                  f"ioengine={workflow.global_fio.ioengine}  "
                  f"runtime={workflow.global_fio.runtime}s[/dim]")


@cli.command("analyze")
@click.argument("results_dir")
@click.option("--detailed", "-d", is_flag=True, default=False,
              help="Show per-step latency percentile detail")
def cmd_analyze(results_dir, detailed):
    """
    Analyze and print results from a completed workflow run directory.
    Looks for fio_analysis.json files inside step subdirectories.
    """
    from fio_bench.reporter import print_detailed_analysis, print_fio_summary_table

    results = Path(results_dir)
    if not results.exists():
        console.print(f"[red]Directory not found:[/red] {results_dir}")
        sys.exit(1)

    # Try the pre-built summary first
    summary_file = results / "summary" / "all_fio_results.json"
    analyses = []

    if summary_file.exists():
        analyses = json.loads(summary_file.read_text())
    else:
        # Walk step dirs and collect fio_analysis.json files
        for step_dir in sorted(results.iterdir()):
            analysis_file = step_dir / "fio_analysis.json"
            if analysis_file.exists():
                a = json.loads(analysis_file.read_text())
                a["step_name"]  = a.get("step_name")  or step_dir.name.split("_", 1)[-1]
                a["step_index"] = a.get("step_index") or int(step_dir.name.split("_")[0]) \
                    if step_dir.name[0].isdigit() else 0
                analyses.append(a)

    if not analyses:
        console.print(f"[yellow]No FIO analysis files found in {results_dir}[/yellow]")
        sys.exit(0)

    console.print(Panel(f"[bold]Analysis:[/bold] {results_dir}", border_style="cyan"))
    print_fio_summary_table(analyses, console)

    if detailed:
        for a in analyses:
            print_detailed_analysis(a, console)

    # Show path to HTML report if it exists
    html = results / "summary" / "report.html"
    if html.exists():
        console.print(f"\n[dim]HTML report:[/dim] {html}")


@cli.command("templates")
def cmd_templates():
    """List available workflow templates."""
    templates_dir = Path(__file__).parent / "templates"
    if not templates_dir.exists():
        console.print("[yellow]No templates directory found.[/yellow]")
        return

    from rich.table import Table
    from rich import box
    from fio_bench.workflow import Workflow

    tbl = Table(title="Available Templates", box=box.ROUNDED,
                header_style="bold cyan")
    tbl.add_column("File", style="green")
    tbl.add_column("Name")
    tbl.add_column("Steps", justify="right")
    tbl.add_column("Description", style="dim")

    for f in sorted(templates_dir.glob("*.yaml")):
        try:
            wf = Workflow.from_yaml(f)
            tbl.add_row(f.name, wf.name, str(len(wf.steps)), wf.description)
        except Exception:
            tbl.add_row(f.name, "─", "─", "[red]parse error[/red]")

    console.print(tbl)
    console.print(f"\n[dim]Use with:[/dim]  python fio_bench.py edit templates/<file>")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
