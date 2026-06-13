from __future__ import annotations

from pathlib import Path

import pytest

from leadscout.cache import JsonCache
from leadscout.clients import load_fixture_clients
from leadscout.config import load_geography, load_icp, load_niche

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
EXAMPLES = ROOT / "examples"


@pytest.fixture
def fixture_clients():
    return load_fixture_clients(FIXTURES)


@pytest.fixture
def icp():
    return load_icp(EXAMPLES / "clinic.yaml")


@pytest.fixture
def niche():
    return load_niche(EXAMPLES / "dental.yaml")


@pytest.fixture
def geo():
    return load_geography("Bengaluru")


@pytest.fixture
def cache(tmp_path):
    return JsonCache(tmp_path / "cache")
