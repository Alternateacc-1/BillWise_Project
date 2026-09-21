"""Shared pytest fixtures, and the switch that keeps the suite offline.

scripts/ is not a package, so put it on sys.path once here rather than
repeating the dance in every test module.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# PIN LOCAL MODE BEFORE ANY app IMPORT. conftest is the first thing pytest
# imports, and config.PROVIDER is a module-level constant read once at import,
# so whoever imports app.config first decides the mode for the whole run.
#
# Without this the suite inherited PROVIDER from the shell. A developer who
# had exported PROVIDER=aws to deploy would have had test_api's upload test
# call Textract for real, and Textract bills per page. The eval pins the same
# variable for the same reason; the tests were relying on test_eval importing
# run_eval to do it for them, which is both accidental and too late.
os.environ["PROVIDER"] = "local"

import pytest  # noqa: E402

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
