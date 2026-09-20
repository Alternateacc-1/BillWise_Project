# Docs index

Twelve files, and you almost certainly do not need all of them. Start where
your question is.

---

## Start here

| File | Read it when |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | **Read this first — it is short.** Every ruling that would otherwise get re-litigated, with the measurement behind it. Thresholds, the two-reader design, why gray is a correct answer, the product's language rules. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | You want to know how a bill becomes a report. The pipeline, stage by stage. |
| [`LIMITS.md`](LIMITS.md) | Before "fixing" something. What the tool cannot do, each with the measurement that established it, plus the full security audit. |

## Going deeper

| File | Read it when |
|---|---|
| [`FORMAT_FINDINGS.md`](FORMAT_FINDINGS.md) | You are working on bill parsing. What broke across eight real-world bill formats, recorded before anything was fixed. Includes the accidental one-reader/two-reader experiment. |
| [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) | You are looking for something worth doing. Unresolved questions, with what is known about each. |

## Operations

| File | Read it when |
|---|---|
| [`SELF_HOSTING.md`](SELF_HOSTING.md) | **You want to run this yourself.** Local setup in ten minutes, and the ordered path to deploying it into your own AWS account, with what it costs and what the second reader is optional for. |
| [`AWS_STEPS.md`](AWS_STEPS.md) | You are deploying, or something in AWS is behaving strangely. Every console step and command, written for someone who has never used AWS — including the six environment failures on the first deploy and exactly what each one actually meant. Section 11 is the frontend redeploy. |

## Contributing

| File | Read it when |
|---|---|
| [`FRONTEND_BRIEF.md`](FRONTEND_BRIEF.md) | You are picking up frontend work. Self-contained — it is written to be handed to someone who has never seen the project. Includes "five things that look like clutter and are not". |
| [`CHANGES_TEMPLATE.md`](CHANGES_TEMPLATE.md) | You are about to start. Copy it to `CHANGES_BY_<yourname>.md` and log as you go. |
| [`CHANGES_BY_contributor.md`](CHANGES_BY_contributor.md) | You are changing the report UI. the contributor's log of the report redesign — the teaser column and detailed-analysis carousel — with his measurements and the calls he made. |

## Demo and submission

| File | Read it when |
|---|---|
| [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md) | Recording the full 5–6 minute demo video. |
| [`VIDEO_SCRIPT_3MIN.md`](VIDEO_SCRIPT_3MIN.md) | Recording the 3-minute technical cut — stack, architecture, AWS, lessons. |
| [`VIDEO_CUECARD.md`](VIDEO_CUECARD.md) | Actually filming. Glance-don't-read version of the full script. |

---

## Two habits worth copying from this codebase

**Measure before you conclude.** The working notes were confidently wrong
three times in a single day about what was broken, and each time a
five-minute script settled it. The `eval/*_probe.py` scripts exist for exactly
that. If you are about to act on something a document asserts, check whether
it is still true first.

**Never state a number you did not derive.** Not in the UI, not in the docs,
not in the video. Every figure in these files was measured, and several were
corrected after turning out to be stale. If you add one, say where it came
from.
