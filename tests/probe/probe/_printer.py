from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich import box

console = Console()


@dataclass
class Result:
    label: str
    status_code: int
    duration_ms: int
    body: Any = None
    contract: str | None = None
    valid: bool | None = None
    errors: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)  # key insights shown in summary
    connection_error: str | None = None
    expected_status_code: int | None = None  # non-2xx but expected (e.g. 404 when no data yet)

    @property
    def ok(self) -> bool:
        if self.connection_error:
            return False
        if self.expected_status_code is not None:
            return self.status_code == self.expected_status_code
        return 200 <= self.status_code < 300


class Printer:
    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose

    def section(self, title: str, url: str) -> None:
        console.print()
        console.rule(f"[bold cyan]{title}[/]  [dim]{url}[/dim]")
        console.print()

    def result(self, r: Result) -> None:
        # ── Status line ──────────────────────────────────────────────
        if r.connection_error:
            icon, _color = "🔌", "red"
            status_text = f"[red]UNREACHABLE[/]  {r.connection_error}"
        elif r.ok:
            icon, _color = "✅", "green"
            status_text = f"[green]{r.status_code} OK[/]  [dim]({r.duration_ms}ms)[/dim]"
        else:
            icon, _color = "❌", "red"
            status_text = f"[red]{r.status_code}[/]  [dim]({r.duration_ms}ms)[/dim]"

        console.print(f"  {icon} [bold]{r.label}[/]  {status_text}")

        if r.connection_error:
            console.print()
            return

        # ── Contract validation ───────────────────────────────────────
        if r.contract and r.valid is not None:
            if r.valid:
                console.print(f"     [green]✓[/] [dim]contract:[/] {r.contract}.json")
            else:
                console.print(f"     [red]✗[/] [dim]contract:[/] {r.contract}.json")
                for err in r.errors[:3]:
                    console.print(f"       [red]→[/] {err}")

        # ── Key notes ─────────────────────────────────────────────────
        for key, val in r.notes.items():
            if isinstance(val, list):
                console.print(f"     [dim]{key:<22}[/] {', '.join(str(v) for v in val[:5])}")
            elif isinstance(val, bool):
                mark = "[green]✓[/]" if val else "[red]✗[/]"
                console.print(f"     [dim]{key:<22}[/] {mark}")
            else:
                console.print(f"     [dim]{key:<22}[/] {val}")

        # ── Full JSON (verbose) ───────────────────────────────────────
        if self.verbose and r.body is not None:
            body_str = json.dumps(r.body, ensure_ascii=False, indent=2)
            # Truncate very large bodies
            if len(body_str) > 4000:
                body_str = body_str[:4000] + "\n... (truncated)"
            console.print(Syntax(body_str, "json", theme="monokai", background_color="default"))

        console.print()

    def chat_turn(
        self,
        turn: int,
        user_msg: str,
        assistant_msg: str,
        *,
        analysis_triggered: bool = False,
        duration_ms: int = 0,
    ) -> None:
        console.print(f"  [bold cyan]Turn {turn}[/]  [dim]({duration_ms}ms)[/dim]")
        console.print(f"     [bold]→[/] {user_msg}")

        # Wrap long responses
        short = assistant_msg[:200] + ("..." if len(assistant_msg) > 200 else "")
        console.print(f"     [bold cyan]←[/] {short}")

        if analysis_triggered:
            console.print("     [yellow]⟳[/] background analysis triggered")
        console.print()

    def gap_analysis(self, gap: dict) -> None:
        console.print()
        console.print("  [bold]Gap Analysis[/]  [dim](director → Claude)[/dim]")
        score = gap.get("completeness_score", 0)
        bar = _progress_bar(score)
        console.print(f"     [dim]{'completeness':<22}[/] {bar}  {int(score * 100)}%")

        gaps = gap.get("gaps", [])
        if gaps:
            _gap_table(gaps)

        console.print()

    def summary_table(self, results: list[Result]) -> None:
        total = len(results)
        ok = sum(1 for r in results if r.ok)
        validated = [r for r in results if r.valid is not None]
        valid_count = sum(1 for r in validated if r.valid)

        console.rule("[bold]Summary[/]")
        console.print()
        status = "[green]ALL PASS[/]" if ok == total else f"[yellow]{ok}/{total} passed[/]"
        console.print(f"  Endpoints : {status}")
        if validated:
            cv = (
                "[green]ALL VALID[/]"
                if valid_count == len(validated)
                else f"[yellow]{valid_count}/{len(validated)} valid[/]"
            )
            console.print(f"  Contracts : {cv}")
        console.print()


# ── helpers ──────────────────────────────────────────────────────────────────


def _note(key: str, val: str) -> None:
    short = val[:120] + ("..." if len(val) > 120 else "")
    console.print(f"     [dim]{key:<22}[/] {short}")


def _progress_bar(score: float, width: int = 20) -> str:
    filled = int(score * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if score >= 0.7 else "yellow" if score >= 0.4 else "red"
    return f"[{color}]{bar}[/]"


def _gap_table(gaps: list[dict]) -> None:
    t = Table(box=box.SIMPLE, show_header=True, header_style="bold dim", padding=(0, 1))
    t.add_column("Priority", width=8)
    t.add_column("Field", width=18)
    t.add_column("User question")

    priority_colors = {"high": "red", "medium": "yellow", "low": "dim"}
    for g in gaps:
        pri = g.get("priority", "medium")
        color = priority_colors.get(pri, "dim")
        t.add_row(
            f"[{color}]{pri}[/]",
            g.get("field", ""),
            g.get("user_friendly_question", g.get("description", ""))[:80],
        )

    console.print(t)
