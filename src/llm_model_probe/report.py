"""Terminal table + markdown + json rendering."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table

from .models import Endpoint, ModelResult


@dataclass
class EndpointSnapshot:
    endpoint: Endpoint
    results: list[ModelResult]


def mask_api_key(key: str) -> str:
    if len(key) < 12:
        return "*****"
    return f"{key[:4]}...{key[-4:]}"


def relative_time(when: datetime | None) -> str:
    if not when:
        return "never"
    delta = datetime.now() - when
    seconds = int(delta.total_seconds())
    if seconds < 30:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


def render_list_table(
    snapshots: Iterable[EndpointSnapshot], console: Console | None = None
) -> None:
    """Render the `probe list` table to terminal."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("SDK")
    table.add_column("Mode")
    table.add_column("Status", justify="right")
    table.add_column("Tested")
    table.add_column("Note")

    for snap in snapshots:
        ep = snap.endpoint
        ok = sum(1 for r in snap.results if r.status == "available")
        fail = sum(1 for r in snap.results if r.status == "failed")
        if ep.list_error:
            status = "[red]list-error[/red]"
        elif not snap.results:
            status = "[yellow]not probed[/yellow]"
        else:
            status = f"[green]{ok}[/green]/[red]{fail}[/red]"
        latest = max(
            (r.last_tested_at for r in snap.results if r.last_tested_at),
            default=None,
        )
        table.add_row(
            ep.id,
            ep.name,
            ep.sdk,
            ep.mode,
            status,
            relative_time(latest),
            (ep.note[:40] + "…") if len(ep.note) > 40 else ep.note,
        )

    (console or Console()).print(table)


def render_show(snap: EndpointSnapshot, console: Console | None = None) -> None:
    """Render `probe show <name>` detail view."""
    c = console or Console()
    ep = snap.endpoint
    c.print(f"\n[bold cyan]{ep.name}[/bold cyan] ([dim]{ep.id}[/dim])")
    c.print(f"  SDK     : {ep.sdk}")
    c.print(f"  URL     : {ep.base_url}")
    c.print(f"  API key : {mask_api_key(ep.api_key)}")
    c.print(f"  Mode    : {ep.mode}")
    if ep.note:
        c.print(f"  Note    : {ep.note}")
    if ep.list_error:
        c.print(f"  [red]List error[/red]: {ep.list_error}")
    c.print()

    if not snap.results:
        c.print("[yellow]No probe results yet. Run `probe retest`.[/yellow]")
        return

    ok = [r for r in snap.results if r.status == "available"]
    fail = [r for r in snap.results if r.status == "failed"]

    if ok:
        t = Table(title=f"Available ({len(ok)})", title_style="bold green")
        t.add_column("Model")
        t.add_column("Latency", justify="right")
        t.add_column("Preview")
        for r in ok:
            t.add_row(
                r.model_id,
                f"{r.latency_ms} ms" if r.latency_ms is not None else "-",
                (r.response_preview or "")[:60],
            )
        c.print(t)

    if fail:
        t = Table(title=f"Failed ({len(fail)})", title_style="bold red")
        t.add_column("Model")
        t.add_column("Error")
        t.add_column("Message")
        for r in fail:
            t.add_row(
                r.model_id,
                r.error_type or "-",
                (r.error_message or "")[:80],
            )
        c.print(t)


def render_markdown(snapshots: Iterable[EndpointSnapshot]) -> str:
    snapshots = list(snapshots)
    lines = [
        "# LLM Model Probe Report",
        "",
        f"_Generated: {datetime.now().isoformat(timespec='seconds')}_",
        "",
        "## Summary",
        "",
        "| Endpoint | SDK | Mode | Available | Failed | Tested |",
        "|---|---|---|---:|---:|---|",
    ]
    for snap in snapshots:
        ep = snap.endpoint
        ok = sum(1 for r in snap.results if r.status == "available")
        fail = sum(1 for r in snap.results if r.status == "failed")
        latest = max(
            (r.last_tested_at for r in snap.results if r.last_tested_at),
            default=None,
        )
        lines.append(
            f"| {ep.name} | {ep.sdk} | {ep.mode} | {ok} | {fail} | "
            f"{relative_time(latest)} |"
        )
    lines.append("")

    for snap in snapshots:
        ep = snap.endpoint
        lines.append(f"## {ep.name} (`{ep.sdk}`)")
        lines.append("")
        lines.append(f"- Base URL: `{ep.base_url}`")
        lines.append(f"- Mode: `{ep.mode}`")
        if ep.note:
            lines.append(f"- Note: {ep.note}")
        if ep.list_error:
            lines.append(f"- **List error**: `{ep.list_error}`")
        lines.append("")
        ok_results = [r for r in snap.results if r.status == "available"]
        fail_results = [r for r in snap.results if r.status == "failed"]
        if ok_results:
            lines.append(f"### Available ({len(ok_results)})")
            lines.append("")
            lines.append("| Model | Latency | Preview |")
            lines.append("|---|---:|---|")
            for r in ok_results:
                preview = (r.response_preview or "").replace("|", "\\|").replace("\n", " ")
                latency = f"{r.latency_ms} ms" if r.latency_ms is not None else "-"
                lines.append(f"| `{r.model_id}` | {latency} | {preview} |")
            lines.append("")
        if fail_results:
            lines.append(f"### Failed ({len(fail_results)})")
            lines.append("")
            lines.append("| Model | Error | Message |")
            lines.append("|---|---|---|")
            for r in fail_results:
                msg = (r.error_message or "").replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| `{r.model_id}` | {r.error_type or '-'} | {msg[:140]} |"
                )
            lines.append("")
    return "\n".join(lines)


def render_json(snapshots: Iterable[EndpointSnapshot]) -> str:
    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "endpoints": [],
    }
    for snap in snapshots:
        ep = snap.endpoint
        payload["endpoints"].append(
            {
                "id": ep.id,
                "name": ep.name,
                "sdk": ep.sdk,
                "base_url": ep.base_url,
                "mode": ep.mode,
                "note": ep.note,
                "list_error": ep.list_error,
                "results": [
                    {
                        "model": r.model_id,
                        "source": r.source,
                        "status": r.status,
                        "latency_ms": r.latency_ms,
                        "error_type": r.error_type,
                        "error_message": r.error_message,
                        "response_preview": r.response_preview,
                        "last_tested_at": (
                            r.last_tested_at.isoformat(timespec="seconds")
                            if r.last_tested_at
                            else None
                        ),
                    }
                    for r in snap.results
                ],
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)
