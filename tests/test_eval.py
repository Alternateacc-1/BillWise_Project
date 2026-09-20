"""Phase 2: the eval suite is the gate on "zero false reds".

These tests make the claim in the pitch a thing CI can fail on, rather than a
number someone read off a terminal once.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "eval"))

import run_eval  # noqa: E402

GROUND_TRUTH = REPO_ROOT / "eval" / "ground_truth"
FIXTURES = REPO_ROOT / "eval" / "fixtures"
DEMO_BILLS = REPO_ROOT / "eval" / "demo_bills"

#: The demo bills are GENERATED, not committed -- they are synthetic and
#: regenerable, so the repo carries the generator rather than its output.
#: A fresh clone has the fixtures (which the eval actually scores against)
#: but not the rendered PDFs, so the artefact tests skip with a message
#: telling you the one command that fixes it, rather than failing.
needs_demo_bills = pytest.mark.skipif(
    not (DEMO_BILLS / "bill_01.pdf").exists(),
    reason="demo bills not generated -- run: python scripts/make_demo_bills.py",
)

BILL_IDS = sorted(p.stem for p in GROUND_TRUTH.glob("bill_*.json"))


@pytest.fixture(scope="module")
def results() -> list[dict]:
    assert BILL_IDS, "no ground truth; run scripts/make_demo_bills.py"
    return [run_eval.run_one(bill_id) for bill_id in BILL_IDS]


# --------------------------------------------------------------------------
# The hard gate
# --------------------------------------------------------------------------

def test_zero_false_reds(results):
    """The one number that must never move.

    A false red means telling a patient their hospital charged above a
    published ceiling when it did not. There is no acceptable non-zero value.
    """
    offenders = [
        (r["bill_id"], entry)
        for r in results for entry in r["false_reds"]
    ]
    assert offenders == [], f"{len(offenders)} false red(s): {offenders}"


def test_nothing_planted_is_missed(results):
    missed = [
        (r["bill_id"], entry)
        for r in results for entry in r["missed"]
    ]
    assert missed == [], f"{len(missed)} missed finding(s): {missed}"


def test_gray_reasons_are_the_expected_ones(results):
    """A right verdict for the wrong reason is still wrong."""
    wrong = [
        (r["bill_id"], entry)
        for r in results for entry in r["wrong_gray_reason"]
    ]
    assert wrong == [], f"{len(wrong)} item(s) gray for the wrong reason: {wrong}"


def test_the_eval_runner_exits_zero(capsys):
    assert run_eval.main() == 0
    out = capsys.readouterr().out
    assert "FALSE REDS" in out
    assert "PASS" in out


# --------------------------------------------------------------------------
# The required plants
# --------------------------------------------------------------------------

def _expected(bill_id: str) -> list[dict]:
    return json.loads(
        (GROUND_TRUTH / f"{bill_id}.json").read_text(encoding="utf-8")
    )["expected"]


def _all_expected() -> list[dict]:
    return [e for b in BILL_IDS for e in _expected(b)]


def test_all_six_required_plants_exist():
    """Exactly the set the brief names, all present across the suite."""
    everything = _all_expected()
    whys = " ".join(e.get("why", "") for e in everything).lower()

    reds = [e for e in everything if e["severity"] == "red"]
    assert any("augmentin" in e["item_name"].lower() for e in reds), \
        "missing: a branded medicine above its ceiling"
    assert any("stent" in e["item_name"].lower() for e in reds), \
        "missing: a stent above its ceiling"

    assert any(e["rule_id"] == "R1" for e in everything), \
        "missing: an arithmetic error"
    assert any(e["rule_id"] == "R3" for e in everything), \
        "missing: a duplicated consumable"
    assert any(e["severity"] == "green" for e in everything), \
        "missing: a correctly priced item that must stay green"
    assert any(
        e.get("gray_reason") == "could_not_verify" for e in everything
    ), "missing: a deliberately blurry line"
    assert "plant" in whys


def test_the_amber_band_is_exercised(results):
    """A metric that is permanently zero is a metric nobody has tested."""
    in_band = [e for r in results for e in r["amber_band"]]
    assert in_band, "no item lands in the 0-25% band; the metric is untested"
    for entry in in_band:
        excess = float(entry["excess_pct"])
        assert 0 < excess <= 25


def test_both_gray_reasons_appear(results):
    assert sum(r["no_public_ceiling"] for r in results) > 0
    assert sum(r["could_not_verify"] for r in results) > 0


def test_the_gray_majority_is_real(results):
    """The bills must look like real bills, not like a flag showcase.

    If most lines were priceable, the demo would misrepresent what this
    system can actually check.
    """
    total_gray = sum(
        r["no_public_ceiling"] + r["could_not_verify"] for r in results
    )
    total_lines = sum(r["lines"] for r in results)
    assert total_gray > total_lines * 0.5, (
        f"only {total_gray}/{total_lines} lines are gray; the demo bills are "
        f"not shaped like real hospital bills"
    )


# --------------------------------------------------------------------------
# Artefacts and safety
# --------------------------------------------------------------------------

@needs_demo_bills
@pytest.mark.parametrize("bill_id", BILL_IDS)
def test_every_bill_has_a_fixture_and_a_pdf(bill_id):
    assert (FIXTURES / f"{bill_id}.json").exists()
    assert (DEMO_BILLS / f"{bill_id}.pdf").exists()


@needs_demo_bills
def test_a_noisy_scan_exists():
    assert (DEMO_BILLS / "bill_05.jpg").exists()


def test_no_demo_bill_contains_a_patient_name():
    """Fake hospital, no patient names, nothing real. Ever."""
    banned = ("patient name:", "mr.", "mrs.", "aadhaar", "uhid no")
    for bill_id in BILL_IDS:
        text = (FIXTURES / f"{bill_id}.json").read_text(encoding="utf-8").lower()
        for token in banned:
            assert token not in text, f"{bill_id} contains {token!r}"
        assert "sample" in text


def test_the_eval_is_pinned_to_local_mode():
    """The eval is the thing most likely to be run in a loop.

    It must never be able to reach a paid API.
    """
    import os
    assert os.environ.get("PROVIDER") == "local"
    from app import config
    assert config.PROVIDER == "local"


def test_the_gray_split_is_pinned(results):
    """The split is a CLAIM about what this tool can and cannot check.

    Pinned deliberately, so that a change to gray-reason semantics has to be
    argued for rather than absorbed silently.

    MOVED TWICE, both on 2026-09-19.

    26/8 -> 25/9 when the REDUCED brand index shipped. One line moved:
    bill_06 line 3, SINALATE = CAFFEINE + DIPHENHYDRAMINE. Diphenhydramine
    appears in ZERO ceiling rows, so the member-rule filter drops the brand
    and the deployed data cannot identify it. That is ACCURATE: with what
    ships we hold nothing about that molecule. The alternative -- shipping the
    full 36 MB index so it reads no_public_ceiling -- was rejected on cold
    start, and local now uses the same file as production so the two cannot
    disagree.

    23/11 -> 26/8 when R9 gained a third branch: a drug that RESOLVES
    COMPLETELY but has no row in the published list is no_public_ceiling, not
    could_not_identify. Three lines moved, all verified individually:

      bill_02 line 5  Pantoprazole 40mg Tablet -- resolves fully; the list
                      holds only PANTOPRAZOLE INJECTION 40 MG, no tablet row
      bill_06 line 1  PANTOCID DSR CAP -- DOMPERIDONE + PANTOPRAZOLE capsule;
                      the combination is absent from the 915
      bill_06 line 3  SINALATE TAB -- CAFFEINE + DIPHENHYDRAMINE; the latter
                      has no ceiling row at all

    If this assertion fails, do NOT re-pin it without checking the same way:
    a line moving INTO no_public_ceiling must have resolved completely first,
    or the tool is overstating what it knows.
    """
    no_ceiling = sum(r["no_public_ceiling"] for r in results)
    could_not_verify = sum(r["could_not_verify"] for r in results)
    assert (no_ceiling, could_not_verify) == (25, 9), (
        f"gray split moved to {no_ceiling}/{could_not_verify}; verify each "
        "moved line resolved completely before re-pinning"
    )
