"""Run configuration and YAML/.env loading. Config is data, never code."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from .models import GeographyInput, ICPSpec, NicheSpec

# Cheap/fast model for the per-lead scoring step (idea.md §7: "use a cheaper/faster model").
DEFAULT_SCORING_MODEL = "gpt-4o-mini"
DEFAULT_BUDGET_USD = 2.00


class RunConfig(BaseModel):
    """Everything a run needs that is not the ICP/niche/geo data itself."""

    scoring_model: str = DEFAULT_SCORING_MODEL
    budget_usd: float = DEFAULT_BUDGET_USD
    max_score: int | None = None  # cap how many survivors reach the LLM (cost guard)
    offline: bool = False  # wire fixture clients instead of live APIs
    out_dir: Path = Path("out")
    cache_dir: Path = Path(".cache")
    db_path: Path = Path(".cache/leadscout.db")
    # Stage 3 politeness
    max_concurrency: int = 5
    request_timeout_s: float = 10.0

    @classmethod
    def from_env(cls, **overrides: object) -> RunConfig:
        load_dotenv()
        env_defaults: dict[str, object] = {}
        if model := os.getenv("LEADSCOUT_SCORING_MODEL"):
            env_defaults["scoring_model"] = model
        if budget := os.getenv("LEADSCOUT_BUDGET_USD"):
            env_defaults["budget_usd"] = float(budget)
        env_defaults.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**env_defaults)


def _load_yaml(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    return data


def load_icp(path: str | Path) -> ICPSpec:
    return ICPSpec.model_validate(_load_yaml(path))


def load_niche(path: str | Path) -> NicheSpec:
    return NicheSpec.model_validate(_load_yaml(path))


def load_geography(geo: str | Path) -> GeographyInput:
    """Accept either a YAML path or a bare city name passed on the CLI."""
    p = Path(geo)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        return GeographyInput.model_validate(_load_yaml(p))
    return GeographyInput(city=str(geo))


def require_key(name: str) -> str:
    """Fetch a required secret from the environment, or fail loudly (never hardcode)."""
    load_dotenv()
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Missing {name}. Set it in .env (see .env.example). "
            f"For an offline run, pass --offline."
        )
    return val
