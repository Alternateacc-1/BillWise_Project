"""Shared pytest fixtures.

scripts/ is not a package, so put it on sys.path once here rather than
repeating the dance in every test module.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import prepare_reference as pr  # noqa: E402


@pytest.fixture(scope="session")
def rows() -> list:
    """All reference rows, parsed fresh from data/raw/.

    Parses the sources rather than reading the generated CSV, so the tests
    validate the parser itself and cannot be fooled by a stale artefact.
    """
    return pr.build()


@pytest.fixture(scope="session")
def ceiling(rows) -> list:
    return [r for r in rows if r.source == "ceiling"]


@pytest.fixture(scope="session")
def special(rows) -> list:
    return [r for r in rows if r.source == "special_feature"]


@pytest.fixture(scope="session")
def retail(rows) -> list:
    return [r for r in rows if r.source == "retail_new_drug"]
