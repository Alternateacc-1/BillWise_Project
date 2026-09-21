# Docs

Six files. Start where your question is — you almost certainly do not need
all of them.

The [main README](../README.md) covers what BillWise does, how to run it
locally, and what it cannot do. These go deeper.

---

| If you want to | Read |
|---|---|
| know why the engine behaves the way it does | [`DECISIONS.md`](DECISIONS.md) |
| understand how a bill becomes a report | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| know what the tool cannot do, and how we know | [`LIMITS.md`](LIMITS.md) |
| run it yourself, locally or on your own AWS | [`SELF_HOSTING.md`](SELF_HOSTING.md) |
| deploy step by step, or fix a broken deploy | [`AWS_STEPS.md`](AWS_STEPS.md) |
| change the interface | [`FRONTEND_BRIEF.md`](FRONTEND_BRIEF.md) |

**[`DECISIONS.md`](DECISIONS.md) is the one to read first.** It is short, and
it holds every ruling that would otherwise get argued twice: the thresholds and
why each number, why there are two readers, why "we could not check this" is a
correct answer, and the words the product will not use.

There is also [`../data/README.md`](../data/README.md), which explains what is
in `data/` — what each file is, what reads it, and why the retail price rows
are kept even though the engine never prices from them.

---

## Two habits worth copying

**Measure before you conclude.** These notes have been confidently wrong about
what was broken, and each time a short script settled it in minutes. If you are
about to act on something a document here asserts, check whether it is still
true — `eval/run_eval.py` and `eval/adversarial_audit.py` are one command each.

**Never state a number you did not derive.** Not in the interface, not in a
doc, not in a commit message. Every figure in these files was measured, and
several were corrected after turning out to be stale.
