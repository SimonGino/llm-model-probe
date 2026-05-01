"""Typer-based CLI."""
from __future__ import annotations

import asyncio
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
