"""
Interactive TUI workflow builder using Rich.

Renders the step pipeline visually and lets the user add/edit/delete/reorder
steps through a simple prompt-driven interface (no raw-terminal curses needed).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .workflow import (
    CMD_PRESETS,
    FIO_PRESETS,
    CommandEntry,
    FIOJobConfig,
    GlobalFIOConfig,
    Workflow,
    WorkflowStep,
)

console = Console()


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _clear() -> None:
    os.system("clear" if os.name != "nt" else "cls")


def _step_panel(step: WorkflowStep, idx: int, selected: bool, total: int) -> Panel:
    badge_color = "cyan"  if step.type == "fio" else "yellow"
    badge       = f"[bold {badge_color}]{step.type_icon()}[/]"
    title_color = "bright_white" if selected else "white"
    star        = " ◄ SELECTED" if selected else ""
    border_style = "cyan" if selected else ("green" if step.enabled else "dim")

    content = Text()
    content.append(f"  {badge}  ")
    content.append(step.name, style=f"bold {title_color}")
    if not step.enabled:
        content.append("  [DISABLED]", style="dim red")
    content.append("\n")

    detail = step.one_liner()
    if detail:
        content.append(f"  {detail}", style="dim")
    if step.description:
        content.append(f"\n  {step.description}", style="italic dim")

    return Panel(
        content,
        title=f"[dim]#{idx:02d}/{total:02d}[/]" + star,
        border_style=border_style,
        padding=(0, 1),
    )


def render_pipeline(workflow: Workflow, selected_idx: Optional[int] = None) -> None:
    """Render the full workflow pipeline to the terminal."""
    _clear()
    console.print()
    console.print(Panel(
        f"[bold cyan]{workflow.name}[/bold cyan]"
        + (f"\n[dim]{workflow.description}[/dim]" if workflow.description else ""),
        title="[bold]FIO WORKFLOW BUILDER[/bold]",
        border_style="bright_blue",
    ))

    steps = workflow.steps
    if not steps:
        console.print("[dim italic]  (no steps yet — use [a]dd to create one)[/dim italic]\n")
    else:
        for i, step in enumerate(steps):
            panel = _step_panel(step, i + 1, (selected_idx == i), len(steps))
            console.print(panel)
            if i < len(steps) - 1:
                console.print("           [dim]│[/dim]")
                console.print("           [dim]▼[/dim]")

    console.print()
    console.print(Rule(style="dim"))

    # Command legend
    legend_table = Table(box=None, show_header=False, padding=(0, 2))
    legend_table.add_column(style="bold cyan")
    legend_table.add_column(style="dim")
    legend_table.add_row("1..N", "select step")
    legend_table.add_row("a fio | a cmd", "add step (at end or after selected)")
    legend_table.add_row("e", "edit selected step")
    legend_table.add_row("d", "delete selected step")
    legend_table.add_row("u / dn", "move selected step up / down")
    legend_table.add_row("t", "toggle enable/disable selected")
    legend_table.add_row("g", "edit global FIO settings")
    legend_table.add_row("r", "run workflow")
    legend_table.add_row("x", "export standalone shell script")
    legend_table.add_row("s", "save workflow YAML")
    legend_table.add_row("q", "quit")

    console.print(legend_table)
    console.print()


# ---------------------------------------------------------------------------
# Step editors
# ---------------------------------------------------------------------------

def _prompt_str(label: str, default: str = "") -> str:
    if default:
        return Prompt.ask(f"  [cyan]{label}[/cyan]", default=str(default))
    return Prompt.ask(f"  [cyan]{label}[/cyan]")


def _prompt_int(label: str, default: int = 0) -> int:
    return IntPrompt.ask(f"  [cyan]{label}[/cyan]", default=default)


def _choose_fio_preset() -> dict:
    console.print("\n[bold]FIO Presets:[/bold]")
    keys = list(FIO_PRESETS.keys())
    for i, k in enumerate(keys, start=1):
        console.print(f"  {i}. {FIO_PRESETS[k]['label']}")
    choice = IntPrompt.ask("  Choose preset", default=8 if len(keys) >= 8 else 1)
    if 1 <= choice <= len(keys):
        return FIO_PRESETS[keys[choice - 1]]["fio"].copy()
    return FIO_PRESETS["custom"]["fio"].copy()


def _choose_cmd_preset() -> list:
    console.print("\n[bold]Command Presets:[/bold]")
    keys = list(CMD_PRESETS.keys())
    for i, k in enumerate(keys, start=1):
        console.print(f"  {i}. {CMD_PRESETS[k]['label']}")
    choice = IntPrompt.ask("  Choose preset", default=len(keys))
    if 1 <= choice <= len(keys):
        return [dict(c) for c in CMD_PRESETS[keys[choice - 1]]["commands"]]
    return [{"cmd": "echo hello", "label": "test"}]


def _edit_fio_step(step: WorkflowStep) -> WorkflowStep:
    console.print(f"\n[bold]Editing FIO step:[/bold] {step.name}")
    step.name = _prompt_str("Step name", step.name)
    step.description = _prompt_str("Description (optional)", step.description)

    fio = step.fio or FIOJobConfig()
    console.print("\n[bold]FIO parameters[/bold] (Enter to keep current):")
    fio.rw       = _prompt_str("rw (read/write/randread/randwrite/randrw/rw)", fio.rw)
    fio.bs       = _prompt_str("bs (block size, e.g. 4k / 128k)", fio.bs)
    fio.iodepth  = _prompt_int("iodepth", fio.iodepth)
    fio.numjobs  = _prompt_int("numjobs (0 = inherit global)", fio.numjobs or 0) or None

    if "rw" in fio.rw and fio.rw not in ("read", "write"):
        mix = _prompt_str("rwmixread % (read share in mixed mode)", str(fio.rwmixread or 70))
        fio.rwmixread = int(mix) if mix.isdigit() else 70

    # Override global settings?
    if Confirm.ask("  Override runtime for this step?", default=False):
        fio.runtime = _prompt_int("runtime (seconds)", fio.runtime or 60)
    if Confirm.ask("  Override filename/device for this step?", default=False):
        fio.filename = _prompt_str("filename/device", fio.filename or "")

    step.fio = fio
    return step


def _edit_cmd_step(step: WorkflowStep) -> WorkflowStep:
    console.print(f"\n[bold]Editing command step:[/bold] {step.name}")
    step.name = _prompt_str("Step name", step.name)
    step.description = _prompt_str("Description (optional)", step.description)

    console.print("\n[bold]Current commands:[/bold]")
    for i, c in enumerate(step.commands):
        console.print(f"  {i+1}. [{c.label}] {c.cmd}")

    action = Prompt.ask(
        "\n  [cyan]Action[/cyan]",
        choices=["keep", "add", "replace", "delete"],
        default="keep",
    )

    if action == "replace":
        step.commands = []
        action = "add"

    if action == "add":
        console.print("  Enter commands (empty line to finish):")
        while True:
            cmd_str = _prompt_str("  command ('done' to finish)", "done")
            if not cmd_str or cmd_str.lower() == "done":
                break
            label = _prompt_str("  label for this command")
            sudo  = Confirm.ask("  Run with sudo?", default=False)
            ign   = Confirm.ask("  Ignore errors?", default=True)
            step.commands.append(CommandEntry(cmd=cmd_str, label=label, sudo=sudo, ignore_errors=ign))

    elif action == "delete":
        if step.commands:
            idx = _prompt_int(f"  Delete command # (1-{len(step.commands)})", 1)
            if 1 <= idx <= len(step.commands):
                removed = step.commands.pop(idx - 1)
                console.print(f"  Removed: [{removed.label}]")

    return step


def _new_fio_step() -> WorkflowStep:
    console.print("\n[bold cyan]New FIO Step[/bold cyan]")
    preset_fio = _choose_fio_preset()
    step = WorkflowStep(name="", type="fio", fio=FIOJobConfig(**preset_fio))
    step.name = _prompt_str("Step name", preset_fio.get("rw", "fio_step"))
    step.description = _prompt_str("Description (optional)", "")

    if Confirm.ask("  Customize FIO parameters?", default=False):
        step = _edit_fio_step(step)
    return step


def _new_cmd_step() -> WorkflowStep:
    console.print("\n[bold yellow]New Command Step[/bold yellow]")
    preset_cmds = _choose_cmd_preset()
    step = WorkflowStep(
        name="",
        type="command",
        commands=[CommandEntry(**c) for c in preset_cmds],
    )
    step.name = _prompt_str("Step name", "collect_logs")
    step.description = _prompt_str("Description (optional)", "")

    if Confirm.ask("  Customize commands?", default=False):
        step = _edit_cmd_step(step)
    return step


def _edit_global_fio(cfg: GlobalFIOConfig) -> GlobalFIOConfig:
    console.print("\n[bold]Edit Global FIO Settings[/bold]")
    cfg.filename    = _prompt_str("filename / device", cfg.filename)
    cfg.size        = _prompt_str("size (e.g. 1g, 10g)", cfg.size)
    cfg.ioengine    = _prompt_str("ioengine (libaio/io_uring/posixaio/sync)", cfg.ioengine)
    cfg.direct      = _prompt_int("direct (0/1)", cfg.direct)
    cfg.time_based  = _prompt_int("time_based (0/1)", cfg.time_based)
    cfg.runtime     = _prompt_int("runtime (seconds)", cfg.runtime)
    cfg.numjobs     = _prompt_int("numjobs", cfg.numjobs)
    return cfg


# ---------------------------------------------------------------------------
# Main builder loop
# ---------------------------------------------------------------------------

def run_builder(workflow: Workflow, save_path: Optional[Path] = None) -> Workflow:
    """
    Interactive TUI workflow builder. Returns the (possibly modified) workflow.
    save_path: if set, auto-saves to this file on 's' command.
    """
    from .executor import WorkflowExecutor
    from .generator import generate_standalone_script

    selected: Optional[int] = 0 if workflow.steps else None

    while True:
        render_pipeline(workflow, selected_idx=selected)

        try:
            raw = Prompt.ask("[bold green]>[/bold green]").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Interrupted.[/dim]")
            break

        if not raw:
            continue

        tokens = raw.split()
        cmd    = tokens[0]

        # ── select step ────────────────────────────────────────────────────
        if cmd.isdigit():
            n = int(cmd)
            if 1 <= n <= len(workflow.steps):
                selected = n - 1
            else:
                console.print(f"[red]Step {n} not found.[/red]")

        # ── add step ───────────────────────────────────────────────────────
        elif cmd == "a":
            kind = tokens[1] if len(tokens) > 1 else Prompt.ask(
                "  Type", choices=["fio", "cmd"], default="fio"
            )
            if kind in ("fio", "f"):
                new_step = _new_fio_step()
            else:
                new_step = _new_cmd_step()
            # Insert after selected, or at end
            if selected is not None and selected < len(workflow.steps):
                workflow.steps.insert(selected + 1, new_step)
                selected = selected + 1
            else:
                workflow.steps.append(new_step)
                selected = len(workflow.steps) - 1
            console.print(f"  [green]Added:[/green] {new_step.name}")

        # ── edit step ──────────────────────────────────────────────────────
        elif cmd == "e":
            if selected is None or not workflow.steps:
                console.print("[red]Nothing selected.[/red]")
                continue
            step = workflow.steps[selected]
            if step.type == "fio":
                workflow.steps[selected] = _edit_fio_step(step)
            else:
                workflow.steps[selected] = _edit_cmd_step(step)
            console.print(f"  [green]Updated:[/green] {workflow.steps[selected].name}")

        # ── delete step ────────────────────────────────────────────────────
        elif cmd == "d":
            if selected is None or not workflow.steps:
                console.print("[red]Nothing selected.[/red]")
                continue
            name = workflow.steps[selected].name
            if Confirm.ask(f"  Delete '{name}'?", default=False):
                workflow.steps.pop(selected)
                selected = min(selected, len(workflow.steps) - 1) if workflow.steps else None
                console.print(f"  [red]Deleted:[/red] {name}")

        # ── move up ────────────────────────────────────────────────────────
        elif cmd in ("u", "up"):
            if selected and selected > 0:
                workflow.steps[selected], workflow.steps[selected - 1] = \
                    workflow.steps[selected - 1], workflow.steps[selected]
                selected -= 1

        # ── move down ─────────────────────────────────────────────────────
        elif cmd in ("dn", "down"):
            if selected is not None and selected < len(workflow.steps) - 1:
                workflow.steps[selected], workflow.steps[selected + 1] = \
                    workflow.steps[selected + 1], workflow.steps[selected]
                selected += 1

        # ── toggle enable ─────────────────────────────────────────────────
        elif cmd == "t":
            if selected is not None and workflow.steps:
                step = workflow.steps[selected]
                step.enabled = not step.enabled
                state = "enabled" if step.enabled else "disabled"
                console.print(f"  {step.name} → {state}")

        # ── edit global FIO config ─────────────────────────────────────────
        elif cmd == "g":
            workflow.global_fio = _edit_global_fio(workflow.global_fio)

        # ── save ──────────────────────────────────────────────────────────
        elif cmd == "s":
            if save_path is None:
                out = _prompt_str("Save to file", "workflow.yaml")
                save_path = Path(out)
            workflow.save(save_path)
            console.print(f"  [green]Saved:[/green] {save_path}")

        # ── run ───────────────────────────────────────────────────────────
        elif cmd == "r":
            if not workflow.enabled_steps():
                console.print("[red]No enabled steps to run.[/red]")
                continue
            dry = Confirm.ask("  Dry run (no actual execution)?", default=False)
            executor = WorkflowExecutor(
                workflow,
                on_status=lambda msg: console.print(f"  {msg}"),
                dry_run=dry,
            )
            try:
                run_dir = executor.execute()
                console.print(f"\n  [bold green]Complete![/bold green] → {run_dir}")
                from .reporter import print_fio_summary_table
                print_fio_summary_table(executor.fio_analyses, console)
            except Exception as exc:
                console.print(f"  [red]Run failed:[/red] {exc}")
            Prompt.ask("\n  [dim]Press Enter to continue[/dim]", default="")

        # ── export standalone script ───────────────────────────────────────
        elif cmd == "x":
            out_dir = _prompt_str("Export directory", "./fio_standalone")
            script  = generate_standalone_script(workflow, Path(out_dir))
            console.print(f"\n  [green]Exported![/green]")
            console.print(f"  Script:    {script}")
            console.print(f"  FIO jobs:  {Path(out_dir) / 'fio_jobs'}/")
            console.print(f"  Workflow:  {Path(out_dir) / 'workflow.yaml'}")
            Prompt.ask("\n  [dim]Press Enter to continue[/dim]", default="")

        # ── quit ──────────────────────────────────────────────────────────
        elif cmd in ("q", "quit", "exit"):
            if Confirm.ask("  Save before quitting?", default=bool(save_path)):
                if save_path is None:
                    out = _prompt_str("Save to file", "workflow.yaml")
                    save_path = Path(out)
                workflow.save(save_path)
                console.print(f"  [green]Saved:[/green] {save_path}")
            break

        else:
            console.print(f"  [dim]Unknown command: '{raw}'. See legend above.[/dim]")

    return workflow
