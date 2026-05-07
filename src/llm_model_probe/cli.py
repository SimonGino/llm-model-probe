"""Typer-based CLI."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .models import Endpoint, new_endpoint_id
from .probe import ProbeRunner
from .report import EndpointSnapshot, render_list_table, render_show
from .settings import load_settings
from .store import EndpointStore

app = typer.Typer(
    add_completion=False,
    help="Manage and probe OpenAI/Anthropic API endpoints.",
    no_args_is_help=True,
)
console = Console()


def _store() -> EndpointStore:
    s = EndpointStore()
    s.init_schema()
    return s


def _resolve(store: EndpointStore, name_or_id: str) -> Endpoint:
    ep = store.get_endpoint(name_or_id)
    if ep is None:
        raise typer.BadParameter(f"endpoint '{name_or_id}' not found")
    return ep


def _snapshot(store: EndpointStore, ep: Endpoint) -> EndpointSnapshot:
    return EndpointSnapshot(endpoint=ep, results=store.list_model_results(ep.id))


@app.command()
def add(
    name: str = typer.Option(..., "--name", "-n", help="Alias for this endpoint"),
    sdk: str = typer.Option(..., "--sdk", help="openai | anthropic"),
    base_url: str = typer.Option(..., "--base-url", help="API base URL"),
    api_key: str = typer.Option(..., "--api-key", help="API key"),
    models: Optional[str] = typer.Option(
        None,
        "--models",
        help="Comma-separated model IDs to probe; if omitted, auto-discover",
    ),
    note: str = typer.Option("", "--note", help="Free-form note"),
    tags: Optional[str] = typer.Option(
        None, "--tag",
        help="Comma-separated tags, e.g. 'bob,trial'",
    ),
    no_probe: bool = typer.Option(
        False, "--no-probe", help="Skip immediate probing"
    ),
) -> None:
    """Register a new endpoint and probe it immediately."""
    if sdk not in ("openai", "anthropic"):
        raise typer.BadParameter(
            f"sdk must be 'openai' or 'anthropic', got '{sdk}'"
        )
    model_list = [m.strip() for m in (models or "").split(",") if m.strip()]
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    mode = "specified" if model_list else "discover"
    ep = Endpoint(
        id=new_endpoint_id(),
        name=name,
        sdk=sdk,  # type: ignore[arg-type]
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        mode=mode,  # type: ignore[arg-type]
        models=model_list,
        note=note,
        tags=tag_list,
    )
    store = _store()
    try:
        store.insert_endpoint(ep)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    console.print(
        f"[green]✓[/green] added [bold]{ep.name}[/bold] ({ep.id}) — "
        f"mode=[bold]{ep.mode}[/bold]"
    )

    if no_probe:
        console.print("[dim]--no-probe set, skipping probe[/dim]")
        return

    settings = load_settings()
    runner = ProbeRunner(settings, console)
    outcome = asyncio.run(runner.probe_endpoint(ep, allow_partial=False))
    if outcome.list_error:
        store.set_list_error(ep.id, outcome.list_error)
    else:
        store.set_list_error(ep.id, None)
        if outcome.new_results is not None:
            store.replace_model_results(ep.id, outcome.new_results)


@app.command(name="list")
def list_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of table"),
) -> None:
    """List all endpoints with current status."""
    store = _store()
    snaps = [_snapshot(store, ep) for ep in store.list_endpoints()]
    if not snaps:
        console.print("[dim]No endpoints registered. Use `probe add ...`.[/dim]")
        return
    if as_json:
        from .report import render_json

        console.print_json(render_json(snaps))
        return
    render_list_table(snaps, console)


@app.command()
def show(
    name_or_id: str = typer.Argument(..., metavar="NAME_OR_ID"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show detailed probe results for one endpoint."""
    store = _store()
    ep = _resolve(store, name_or_id)
    snap = _snapshot(store, ep)
    if as_json:
        from .report import render_json

        console.print_json(render_json([snap]))
        return
    render_show(snap, console)


@app.command()
def retest(
    name_or_id: Optional[str] = typer.Argument(
        None,
        metavar="NAME_OR_ID",
        help="Endpoint to retest; omit and use --all for all endpoints",
    ),
    all_: bool = typer.Option(False, "--all", help="Retest all endpoints"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Bypass cooldown (retest endpoints tested <24h ago)",
    ),
) -> None:
    """Re-run probing for one or all endpoints."""
    if not name_or_id and not all_:
        raise typer.BadParameter("provide an endpoint name/id or use --all")
    if name_or_id and all_:
        raise typer.BadParameter("--all conflicts with a specific endpoint")

    store = _store()
    settings = load_settings()
    runner = ProbeRunner(settings, console)

    if all_:
        targets = store.list_endpoints()
    else:
        assert name_or_id is not None
        targets = [_resolve(store, name_or_id)]

    if not targets:
        console.print("[dim]No endpoints to retest.[/dim]")
        return

    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(hours=settings.retest_cooldown_hours)
    skipped: list[str] = []
    todo: list[Endpoint] = []
    for ep in targets:
        last = store.last_tested_at(ep.id)
        if all_ and not force and last and last >= cutoff:
            skipped.append(ep.name)
        else:
            todo.append(ep)

    for skipped_name in skipped:
        console.print(
            f"[dim]skip {skipped_name} (within cooldown, "
            f"use --force to override)[/dim]"
        )

    async def run_all() -> None:
        for ep in todo:
            outcome = await runner.probe_endpoint(ep, allow_partial=True)
            if outcome.list_error:
                store.set_list_error(ep.id, outcome.list_error)
            else:
                store.set_list_error(ep.id, None)
            if outcome.new_results is not None:
                store.replace_model_results(ep.id, outcome.new_results)

    asyncio.run(run_all())
    console.print(
        f"[green]✓[/green] retested {len(todo)} endpoint(s)"
        f"{f', skipped {len(skipped)}' if skipped else ''}"
    )


@app.command()
def rm(
    name_or_id: str = typer.Argument(..., metavar="NAME_OR_ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Remove an endpoint (and its probe results)."""
    store = _store()
    ep = _resolve(store, name_or_id)
    if not yes:
        confirm = typer.confirm(f"Delete '{ep.name}' ({ep.id})?")
        if not confirm:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(0)
    store.delete_endpoint(ep.id)
    console.print(f"[green]✓[/green] removed {ep.name}")


@app.command()
def export(
    name_or_id: Optional[str] = typer.Argument(
        None,
        metavar="NAME_OR_ID",
        help="Specific endpoint; omit for all",
    ),
    fmt: str = typer.Option("md", "--format", "-f", help="md | json"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file; default stdout"
    ),
) -> None:
    """Export probe report as Markdown or JSON."""
    if fmt not in ("md", "json"):
        raise typer.BadParameter("format must be 'md' or 'json'")
    store = _store()
    if name_or_id:
        snaps = [_snapshot(store, _resolve(store, name_or_id))]
    else:
        snaps = [_snapshot(store, ep) for ep in store.list_endpoints()]

    from .report import render_json, render_markdown

    text = render_markdown(snaps) if fmt == "md" else render_json(snaps)

    if output:
        from pathlib import Path

        Path(output).write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/green] wrote {output}")
    else:
        print(text)


from .registry_io import dump_endpoints


@app.command()
def dump(
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file; default stdout"
    ),
    include_keys: bool = typer.Option(
        False, "--include-keys",
        help="Include api_key in the output. WARNING: keys are written in plaintext.",
    ),
) -> None:
    """Dump the registry to JSON for re-import on another machine."""
    store = _store()
    payload = dump_endpoints(
        store.list_endpoints(),
        include_keys=include_keys,
    )
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if output:
        out_path = Path(output)
        out_path.write_text(text, encoding="utf-8")
        try:
            out_path.chmod(0o600)
        except OSError:
            pass  # best effort on platforms without chmod
        console.print(
            f"[green]✓[/green] wrote {output} "
            f"({len(payload['endpoints'])} endpoints)"
        )
        if include_keys:
            console.print(
                "[yellow]![/yellow] file contains plaintext API keys; "
                "chmod 0600 applied"
            )
    else:
        print(text)


from .registry_io import (
    LoadConflict,
    LoadFormatError,
    LoadReport,
    load_endpoints,
)


def _print_load_report(report: LoadReport) -> None:
    total_written = len(report.imported) + len(report.replaced)
    detail = ""
    if report.replaced:
        detail = f" (new {len(report.imported)}, replaced {len(report.replaced)})"
    console.print(
        f"[green]✓[/green] imported {total_written} endpoints{detail}"
    )
    if report.skipped:
        names = ", ".join(report.skipped)
        console.print(
            f"  · skipped {len(report.skipped)} conflict(s): {names} "
            "(use --on-conflict=replace to override)"
        )
    if report.missing_keys:
        names = ", ".join(report.missing_keys)
        console.print(
            f"  · {len(report.missing_keys)} endpoint(s) have no api_key: "
            f"{names} — fill in via the web UI's edit dialog"
        )


@app.command()
def load(
    path: str = typer.Argument(..., metavar="FILE"),
    on_conflict: str = typer.Option(
        "skip", "--on-conflict",
        help="Strategy when an endpoint name already exists: skip | replace | error",
    ),
) -> None:
    """Load endpoints from a `probe dump` file."""
    if on_conflict not in ("skip", "replace", "error"):
        raise typer.BadParameter("--on-conflict must be skip | replace | error")

    file = Path(path)
    if not file.exists():
        console.print(f"[red]✗[/red] file not found: {path}")
        raise typer.Exit(1)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as e:
        console.print(f"[red]✗[/red] cannot read {path}: {e}")
        raise typer.Exit(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        console.print(f"[red]✗[/red] not valid JSON: {e}")
        raise typer.Exit(1)

    store = _store()
    try:
        report = load_endpoints(payload, store, on_conflict=on_conflict)
    except LoadFormatError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except LoadConflict as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(2)

    _print_load_report(report)


@app.command()
def ui(
    port: int = typer.Option(8765, "--port"),
    listen: str = typer.Option(
        "127.0.0.1",
        "--listen",
        help="Bind address. 默认 127.0.0.1 仅本机；公网部署用 0.0.0.0.",
    ),
    no_browser: bool = typer.Option(False, "--no-browser"),
    dev: bool = typer.Option(
        False, "--dev",
        help="Dev mode: assume vite dev server at :5173, skip static mount",
    ),
) -> None:
    """Start the local web UI."""
    import os
    import webbrowser
    from pathlib import Path

    import uvicorn

    is_localhost = listen in ("127.0.0.1", "localhost", "::1")
    if not is_localhost and not os.environ.get("LLM_MODEL_PROBE_TOKEN"):
        console.print(
            "[red]✗[/red] 拒绝绑非-localhost 地址而 LLM_MODEL_PROBE_TOKEN 未设置。\n"
            "  公网/局域网部署前请先 export LLM_MODEL_PROBE_TOKEN=<密钥>。"
        )
        raise typer.Exit(1)

    if dev:
        os.environ["LLM_MODEL_PROBE_DEV"] = "1"
    else:
        pkg_root = Path(__file__).resolve().parents[2]
        dist = pkg_root / "frontend" / "dist"
        if not dist.exists():
            console.print(
                "[red]✗[/red] frontend not built. Run:\n"
                "    cd frontend && npm install && npm run build\n"
                "Or use --dev with `npm run dev` running on :5173."
            )
            raise typer.Exit(1)
        os.environ["LLM_MODEL_PROBE_DIST"] = str(dist)

    url = f"http://{listen}:{port}"
    console.print(f"[green]→[/green] {url}")
    if not no_browser:
        webbrowser.open(url)
    uvicorn.run("llm_model_probe.api:app", host=listen, port=port)
