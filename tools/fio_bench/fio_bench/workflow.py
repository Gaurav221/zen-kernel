"""
Workflow data models: Workflow, WorkflowStep, FIOJobConfig, CommandEntry.
Handles YAML serialization for both GUI and headless use.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

# ---------------------------------------------------------------------------
# FIO presets – named templates the builder can insert directly
# ---------------------------------------------------------------------------
FIO_PRESETS: Dict[str, Dict[str, Any]] = {
    "seq_read": {
        "label": "Sequential Read",
        "fio": {"rw": "read", "bs": "128k", "iodepth": 32, "numjobs": 4},
    },
    "seq_write": {
        "label": "Sequential Write",
        "fio": {"rw": "write", "bs": "128k", "iodepth": 32, "numjobs": 4},
    },
    "rand_read": {
        "label": "Random 4k Read",
        "fio": {"rw": "randread", "bs": "4k", "iodepth": 64, "numjobs": 4},
    },
    "rand_write": {
        "label": "Random 4k Write",
        "fio": {"rw": "randwrite", "bs": "4k", "iodepth": 64, "numjobs": 4},
    },
    "rand_rw_70_30": {
        "label": "Random Mixed 70/30 R/W",
        "fio": {"rw": "randrw", "rwmixread": 70, "bs": "4k", "iodepth": 32, "numjobs": 4},
    },
    "latency_probe": {
        "label": "Latency Probe (QD=1)",
        "fio": {"rw": "randread", "bs": "4k", "iodepth": 1, "numjobs": 1},
    },
    "seq_rw": {
        "label": "Sequential Mixed R/W",
        "fio": {"rw": "rw", "rwmixread": 50, "bs": "128k", "iodepth": 8, "numjobs": 2},
    },
    "custom": {
        "label": "Custom (manual entry)",
        "fio": {"rw": "read", "bs": "4k", "iodepth": 32, "numjobs": 1},
    },
}

# Command presets for common log-collection tasks
CMD_PRESETS: Dict[str, Dict[str, Any]] = {
    "system_info": {
        "label": "System Info",
        "commands": [
            {"cmd": "uname -r", "label": "kernel_version"},
            {"cmd": "lsblk -o NAME,SIZE,TYPE,ROTA,SCHED,MODEL", "label": "block_devices"},
            {"cmd": "cat /proc/cpuinfo | grep 'model name' | head -1", "label": "cpu_model"},
            {"cmd": "free -h", "label": "memory_info"},
        ],
    },
    "disk_stats": {
        "label": "Disk Stats (iostat 5s)",
        "commands": [
            {"cmd": "iostat -x 1 5", "label": "iostat"},
        ],
    },
    "scheduler_info": {
        "label": "I/O Scheduler Info",
        "commands": [
            {"cmd": "cat /sys/block/*/queue/scheduler 2>/dev/null || true", "label": "schedulers"},
            {"cmd": "cat /sys/block/*/queue/nr_requests 2>/dev/null || true", "label": "nr_requests"},
        ],
    },
    "drop_caches": {
        "label": "Drop Page Cache",
        "commands": [
            {"cmd": "sync", "label": "sync"},
            {"cmd": "echo 3 > /proc/sys/vm/drop_caches", "label": "drop_caches", "sudo": True},
        ],
    },
    "custom": {
        "label": "Custom commands",
        "commands": [
            {"cmd": "echo hello", "label": "test"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GlobalFIOConfig:
    """Settings applied to every FIO job unless overridden at step level."""
    filename: str = "/tmp/fio_testfile"
    size: str = "1g"
    ioengine: str = "libaio"
    direct: int = 1
    time_based: int = 1
    runtime: int = 60
    numjobs: int = 1
    group_reporting: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "GlobalFIOConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class FIOJobConfig:
    """Per-step FIO configuration; None fields inherit from GlobalFIOConfig."""
    rw: str = "read"
    bs: str = "4k"
    iodepth: int = 32
    numjobs: Optional[int] = None
    filename: Optional[str] = None
    size: Optional[str] = None
    time_based: Optional[int] = None
    runtime: Optional[int] = None
    ioengine: Optional[str] = None
    direct: Optional[int] = None
    rwmixread: Optional[int] = None
    # Any additional fio options go here
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if v is not None and k != "extra"}
        d.update(self.extra)
        return d

    def summary_line(self) -> str:
        d = self.to_dict()
        parts = [f"{k}={d[k]}" for k in ("rw", "bs", "iodepth", "numjobs") if k in d]
        if "rwmixread" in d:
            parts.append(f"rwmixread={d['rwmixread']}")
        return "  ".join(parts)

    @classmethod
    def from_dict(cls, d: Dict) -> "FIOJobConfig":
        known = set(cls.__dataclass_fields__) - {"extra"}
        extra = {k: v for k, v in d.items() if k not in known}
        kwargs = {k: v for k, v in d.items() if k in known}
        return cls(**kwargs, extra=extra)


@dataclass
class CommandEntry:
    cmd: str
    label: str
    sudo: bool = False
    timeout: int = 120
    ignore_errors: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, d: Dict) -> "CommandEntry":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class WorkflowStep:
    name: str
    type: str  # "fio" | "command"
    description: str = ""
    enabled: bool = True
    fio: Optional[FIOJobConfig] = None
    commands: List[CommandEntry] = field(default_factory=list)

    # ── serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "enabled": self.enabled,
        }
        if self.type == "fio" and self.fio:
            d["fio"] = self.fio.to_dict()
        if self.type == "command" and self.commands:
            d["commands"] = [c.to_dict() for c in self.commands]
        return d

    @classmethod
    def from_dict(cls, d: Dict) -> "WorkflowStep":
        step = cls(
            name=d["name"],
            type=d["type"],
            description=d.get("description", ""),
            enabled=d.get("enabled", True),
        )
        if d["type"] == "fio" and "fio" in d:
            step.fio = FIOJobConfig.from_dict(d["fio"])
        if d["type"] == "command" and "commands" in d:
            step.commands = [CommandEntry.from_dict(c) for c in d["commands"]]
        return step

    # ── display helpers ────────────────────────────────────────────────────

    def type_icon(self) -> str:
        return "◈ FIO" if self.type == "fio" else "⚙ CMD"

    def one_liner(self) -> str:
        if self.type == "fio" and self.fio:
            return self.fio.summary_line()
        if self.type == "command" and self.commands:
            labels = [c.label for c in self.commands[:3]]
            suffix = f" +{len(self.commands) - 3} more" if len(self.commands) > 3 else ""
            return ", ".join(labels) + suffix
        return ""


@dataclass
class Workflow:
    name: str
    description: str = ""
    output_dir: str = "./fio_results"
    global_fio: GlobalFIOConfig = field(default_factory=GlobalFIOConfig)
    steps: List[WorkflowStep] = field(default_factory=list)

    # ── serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "output_dir": self.output_dir,
            "global_fio": self.global_fio.to_dict(),
            "steps": [s.to_dict() for s in self.steps],
        }

    def to_yaml(self) -> str:
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(self.to_yaml())

    @classmethod
    def from_dict(cls, d: Dict) -> "Workflow":
        wf = cls(
            name=d["name"],
            description=d.get("description", ""),
            output_dir=d.get("output_dir", "./fio_results"),
            global_fio=GlobalFIOConfig.from_dict(d.get("global_fio", {})),
        )
        wf.steps = [WorkflowStep.from_dict(s) for s in d.get("steps", [])]
        return wf

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "Workflow":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f))

    # ── helpers ────────────────────────────────────────────────────────────

    def enabled_steps(self) -> List[WorkflowStep]:
        return [s for s in self.steps if s.enabled]

    def clone(self) -> "Workflow":
        return Workflow.from_dict(deepcopy(self.to_dict()))
