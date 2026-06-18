"""CLI entrypoint (idea.md §9):

    leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml

Same binary serves any product by swapping the ICP file. Use --offline for a fixture run with no
keys and no network (the path tests exercise).
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__
from .cache import JsonCache
from .clients import (
    AsyncHttpClient,
    HttpClient,
    LiveHttpClient,
    LiveLlmClient,
    LivePlacesClient,
    LlmClient,
    PlacesClient,
    SourceClient,
    load_fixture_clients,
    load_fixture_sources,
    load_live_sources,
)
from .config import RunConfig, load_geography, load_icp, load_niche, require_key
from .io_out import write_outputs
from .models import LeadState, Source
from .pipeline import run_pipeline
from .store import LeadStore

app = typer.Typer(add_completion=False, help="LeadScout — local lead discovery & qualification.")

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


@app.command()
def run(
    icp: str = typer.Option(..., "--icp", help="Path to ICP YAML."),
    geo: str = typer.Option(..., "--geo", help='City name or geography YAML, e.g. "Bengaluru".'),
    niche: str = typer.Option(..., "--niche", help="Path to niche YAML."),
    offline: bool = typer.Option(False, "--offline", help="Use fixtures; no keys, no network."),
    no_score: bool = typer.Option(False, "--no-score", help="Stop after Stage 3 (no LLM)."),
    max_score: int | None = typer.Option(None, "--max-score", help="Cap survivors sent to LLM."),
    out_dir: str = typer.Option("out", "--out", help="Output directory."),
    db: str | None = typer.Option(None, "--db", help="SQLite DB path."),
) -> None:
    """Run the four-stage pipeline and write ranked leads + a disqualified audit file."""
    icp_spec = load_icp(icp)
    niche_spec = load_niche(niche)
    geography = load_geography(geo)
    cfg = RunConfig.from_env(
        offline=offline,
        max_score=(0 if no_score else max_score),
        out_dir=Path(out_dir),
        db_path=Path(db) if db else None,
    )

    # Extra discovery sources are config-as-data: enabled per niche YAML (Places always canonical).
    extra: list[Source] = [s for s in niche_spec.sources if s != "google_places"]

    places: PlacesClient
    http: HttpClient | AsyncHttpClient
    llm: LlmClient
    sources: list[SourceClient]
    if offline:
        places, http, llm = load_fixture_clients(FIXTURES_DIR)
        sources = list(load_fixture_sources(FIXTURES_DIR, extra))
    else:
        cache = JsonCache(cfg.cache_dir)
        places = LivePlacesClient(
            require_key("GOOGLE_MAPS_API_KEY"),
            cache=cache,
            timeout_s=cfg.request_timeout_s,
        )
        http = LiveHttpClient(
            timeout_s=cfg.request_timeout_s, max_concurrency=cfg.max_concurrency
        )
        llm = LiveLlmClient(require_key("OPENAI_API_KEY"))
        sources = load_live_sources(extra, cache=cache, timeout_s=cfg.request_timeout_s)

    result = run_pipeline(
        geography, niche_spec, icp_spec, cfg, places, http, llm, extra_sources=sources
    )
    paths = write_outputs(result.leads, result.dropped, cfg.out_dir)

    typer.echo(
        f"discovered={result.raw_count}  new={result.new_count}  seen={result.seen_count}  "
        f"candidates={result.candidate_count}  scored={result.scored_count}  "
        f"llm_calls={result.llm_calls}  spent=${result.spent_usd:.4f}"
    )
    typer.echo(f"wrote {paths['csv']}  |  {paths['jsonl']}  |  {paths['disqualified']}")
    if result.leads:
        top = result.leads[0]
        typer.echo(f"top: {top.name}  fit={top.fit_score}  opener=\"{top.suggested_opener}\"")


@app.command()
def mark(
    place_id: str = typer.Argument(..., help="place_id of the lead to update."),
    state: str = typer.Argument(..., help="New state: new, seen, or contacted."),
    db: str | None = typer.Option(None, "--db", help="SQLite DB path."),
) -> None:
    """Manually advance a lead's state (e.g. mark it contacted)."""
    valid: tuple[LeadState, ...] = ("new", "seen", "contacted")
    if state not in valid:
        typer.echo(f"Invalid state '{state}'. Choose from: {', '.join(valid)}", err=True)
        raise typer.Exit(1)
    cfg = RunConfig.from_env(db_path=Path(db) if db else None)
    with LeadStore(cfg.db_path) as store:
        store.set_state(place_id, state)  # type: ignore[arg-type]
    typer.echo(f"{place_id} -> {state}")


@app.command()
def version() -> None:
    typer.echo(f"leadscout {__version__}")


if __name__ == "__main__":
    app()
