"""Probing orchestration: list, filter, and concurrently probe models."""
from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass
from datetime import datetime

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .models import Endpoint, ModelResult
from .providers import make_provider
from .settings import Settings


def filter_models(
    models: list[str], exclude: list[str]
) -> tuple[list[str], list[str]]:
    """Return (kept, skipped) preserving original order, case-insensitive."""
    if not exclude:
        return list(models), []
    patterns = [p.lower() for p in exclude]
    kept: list[str] = []
    skipped: list[str] = []
    for m in models:
        if any(fnmatch.fnmatchcase(m.lower(), p) for p in patterns):
            skipped.append(m)
        else:
            kept.append(m)
    return kept, skipped


@dataclass
class ProbeOutcome:
    """Result of probing one endpoint.

    new_results=None means: don't replace prior results (used when
    list_models() fails on a discover-mode retest).
    """

    list_error: str | None
    new_results: list[ModelResult] | None
    skipped: list[str]


class ProbeRunner:
    def __init__(self, settings: Settings, console: Console | None = None) -> None:
        self._settings = settings
        self._console = console or Console()

    async def probe_endpoint(
        self, ep: Endpoint, *, allow_partial: bool = False
    ) -> ProbeOutcome:
        provider = make_provider(ep, self._settings.timeout_seconds)
        try:
            if ep.mode == "discover":
                try:
                    discovered = await provider.list_models()
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:200]}"
                    self._console.print(
                        f"[red][{ep.name}] list models failed: {err}[/red]"
                    )
                    return ProbeOutcome(
                        list_error=err,
                        new_results=None if allow_partial else [],
                        skipped=[],
                    )
                kept, skipped = filter_models(
                    discovered, self._settings.exclude_patterns
                )
                source: str = "discovered"
            else:
                kept = list(ep.models)
                skipped = []
                source = "specified"

            self._console.print(
                f"[cyan][{ep.name}][/cyan] probing {len(kept)} models "
                f"(skipped {len(skipped)} by filter)"
            )

            results: list[ModelResult] = []
            if kept:
                sem = asyncio.Semaphore(self._settings.concurrency)

                async def one(model_id: str) -> ModelResult:
                    async with sem:
                        pr = await provider.probe(
                            model_id,
                            self._settings.prompt,
                            self._settings.max_tokens,
                        )
                    return ModelResult(
                        endpoint_id=ep.id,
                        model_id=pr.model,
                        source=source,  # type: ignore[arg-type]
                        status="available" if pr.available else "failed",
                        latency_ms=pr.latency_ms,
                        error_type=pr.error_type,
                        error_message=pr.error_message,
                        response_preview=pr.response_preview,
                        last_tested_at=datetime.now(),
                    )

                with Progress(
                    SpinnerColumn(),
                    TextColumn(f"[cyan]{ep.name}[/cyan]"),
                    BarColumn(),
                    MofNCompleteColumn(),
                    TimeElapsedColumn(),
                    console=self._console,
                    transient=True,
                ) as progress:
                    task = progress.add_task("", total=len(kept))
                    tasks = [asyncio.create_task(one(m)) for m in kept]
                    for fut in asyncio.as_completed(tasks):
                        results.append(await fut)
                        progress.advance(task)
                results.sort(key=lambda r: r.model_id)

            ok = sum(1 for r in results if r.status == "available")
            self._console.print(
                f"[cyan][{ep.name}][/cyan] "
                f"[green]✓ {ok}[/green] / [red]✗ {len(results) - ok}[/red]"
            )
            return ProbeOutcome(
                list_error=None, new_results=results, skipped=skipped
            )
        finally:
            await provider.aclose()
