# Docs index

Ten files. You almost certainly do not need all of them — start where your
question is.

---

## Start here

| File | Read it when |
|---|---|
| [`DECISIONS.md`](DECISIONS.md) | **Read this first — it is short.** Every ruling that would otherwise get re-litigated, with the measurement behind it: the thresholds and why each number, the two-reader design, why gray is a correct answer, and the words the product will not use. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | You want to know how a bill becomes a report. The pipeline, stage by stage. |
| [`LIMITS.md`](LIMITS.md) | Before "fixing" something. What the tool cannot do, each with the measurement that established it, plus the security audit. |

## Running it

| File | Read it when |
|---|---|
| [`SELF_HOSTING.md`](SELF_HOSTING.md) | **You want to run this yourself.** Local setup in about ten minutes, then the ordered path to deploying into your own AWS account — what it costs, and why the second reader is optional. |
| [`AWS_STEPS.md`](AWS_STEPS.md) | You are deploying, or something in AWS is behaving strangely. Every console step and command, written for someone who has never used AWS, including the failures hit on the way and what each one actually meant. |

## Going deeper

| File | Read it when |
|---|---|
| [`../data/README.md`](../data/README.md) | You are wondering what is in `data/` — what each file is, what reads it, and why the retail rows are kept when the engine never prices from them. |
| [`FORMAT_FINDINGS.md`](FORMAT_FINDINGS.md) | You are working on bill parsing. What broke across eight real-world bill formats, recorded before anything was fixed. Includes the accidental one-reader / two-reader experiment. |
| [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md) | You are looking for something worth doing. Unresolved questions, with what is known about each. |

## Contributing

| File | Read it when |
|---|---|
| [`FRONTEND_BRIEF.md`](FRONTEND_BRIEF.md) | You are picking up frontend work. Self-contained, written to be handed to someone who has never seen the project. Includes "five things that look like clutter and are not". |
| [`CHANGES_TEMPLATE.md`](CHANGES_TEMPLATE.md) | You are about to start. Copy it to `CHANGES_BY_<yourname>.md` and log as you go. |

---

## Two habits worth copying

**Measure before you conclude.** These notes were confidently wrong more than
once about what was broken, and each time a five-minute script settled it. If
you are about to act on something a document here asserts, check whether it is
still true first — `eval/run_eval.py` and `eval/adversarial_audit.py` are one
command each.

**Never state a number you did not derive.** Not in the interface, not in a
doc, not in a commit message. Every figure in these files was measured, and
several were corrected after turning out to be stale. If you add one, say
where it came from.
