"""CLI entrypoint (idea.md §9):

    leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml

Same binary serves any product by swapping the ICP file. Use --offline for a fixture run with no
keys and no network (the path tests exercise).
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import __version__
from .clients import (
    HttpClient,
    LiveHttpClient,
    LiveLlmClient,
    LivePlacesClient,
    LlmClient,
    PlacesClient,
    load_fixture_clients,
)
from .config import RunConfig, load_geography, load_icp, load_niche, require_key
from .io_out import write_outputs
from .pipeline import run_pipeline

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
) -> None:
    """Run the four-stage pipeline and write ranked leads + a disqualified audit file."""
    icp_spec = load_icp(icp)
    niche_spec = load_niche(niche)
    geography = load_geography(geo)
    cfg = RunConfig.from_env(
        offline=offline, max_score=(0 if no_score else max_score), out_dir=Path(out_dir)
    )

    places: PlacesClient
    http: HttpClient
    llm: LlmClient
    if offline:
        places, http, llm = load_fixture_clients(FIXTURES_DIR)
    else:
        places = LivePlacesClient(require_key("GOOGLE_MAPS_API_KEY"))
        http = LiveHttpClient(cfg.request_timeout_s)
        llm = LiveLlmClient(require_key("OPENAI_API_KEY"))

    result = run_pipeline(geography, niche_spec, icp_spec, cfg, places, http, llm)
    paths = write_outputs(result.leads, result.dropped, cfg.out_dir)

    typer.echo(
        f"discovered={result.raw_count}  candidates={result.candidate_count}  "
        f"scored={result.scored_count}  llm_calls={result.llm_calls}  "
        f"spent=${result.spent_usd:.4f}"
    )
    typer.echo(f"wrote {paths['csv']}  |  {paths['jsonl']}  |  {paths['disqualified']}")
    if result.leads:
        top = result.leads[0]
        typer.echo(f"top: {top.name}  fit={top.fit_score}  opener=\"{top.suggested_opener}\"")


@app.command()
def version() -> None:
    typer.echo(f"leadscout {__version__}")


if __name__ == "__main__":
    app()
