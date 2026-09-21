# Working on the frontend

What you need to know before changing the interface, and the handful of things
in it that look like clutter and are not.

**Setup is in [`SELF_HOSTING.md`](SELF_HOSTING.md)** — clone, install, run,
in about ten minutes with no AWS account. This file is only about the parts
that are easy to break without noticing.

---

## What the interface is for

A patient uploads a photo or PDF of an Indian hospital or pharmacy bill. The
system reads it, compares each line against India's published NPPA ceiling
prices, and shows what may be worth asking about — with the arithmetic and the
government order number behind every claim.

**It is not a fraud detector.** It helps someone ask an informed question.
That framing decides most of the wording choices below.

---

## The one architectural rule

**`frontend/src/lib/api.ts` is the only file that touches the network or knows
the backend's field names.** Everything above it works in UI types, which is
why the entire frontend was once replaced without the pages changing.

Read its header comment before editing it. It names three places where the
engine says more than the UI types originally allowed, and flattening any of
them makes the interface state something untrue.

---

## Five things that look like clutter and are not

Each one is a bug that reached a real screen.

**Reword them freely** — some of the current wording is more technical than a
patient needs. **But do not delete the information they carry.** If you think a
piece of it is not worth carrying, say so in your change log so a maintainer
can disagree before it disappears.

| On screen | Why it is there |
|---|---|
| "We compared **4 of 16** charges" | Without the denominator, a bill where *nothing* could be checked looked identical to a clean one. It rendered "0 things worth asking about" on a bill it had not checked at all. |
| "This does not mean the bill is fine" | The same bug. Falsely reassuring a patient about a medical bill is as damaging as falsely accusing a pharmacy. |
| No "write a letter" button when there are 0 findings | Offering to complain when nothing was found is a credibility leak in the exact place the product earns trust. |
| Separate "could not be read" and "could not be identified" | Different admissions. One blames our reading; the other says the medicine is unknown to us. Collapsing them once claimed we had misread five of six lines we had read perfectly. |
| "N of M lines were seen by only one reader" | The two-reader cross-check is what protects the price rules from a confident misread. When it did not run on a line, the report has to say so. |

The **"Show evidence"** expander is the right pattern for anything technical:
lead with the plain answer, put the machinery behind the expander. The report
currently opens with a short summary and a teaser list, and moves the full
result groups into a "Detailed analysis" carousel below. That was a deliberate
move away from showing everything at once.

---

## Words that never appear in user-facing text

**illegal · fraud · cheating · overcharged**

The product says "may need clarification" and "above the listed ceiling". It
never accuses. This is a deliberate legal and ethical position, not timidity,
and a test fails if any of those four words reaches the interface.

## Gray is a good answer

Roughly half of a real bill comes back gray — not price-controlled, or not
confidently readable. **That is the system working.** Do not redesign gray as
an error state or hide it. A patient learning "we could not check 8 of these 12
charges, and here is why" is being told something true and useful.

---

## Knowing whether you broke something

Two commands, about a minute.

```bash
PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
```

```bash
PYTHONIOENCODING=utf-8 python eval/run_eval.py
```

On a fresh clone that is **253 passed, 48 skipped** and
`caught 46/46 · missed 0 · FALSE REDS 0`. The skips each name the command that
enables them; see the README.

**`FALSE REDS: 0` is the number that matters.** A false red means the system
told a patient a charge was wrong when it was not — a hospital or pharmacy
that billed correctly, publicly doubted by a tool the patient trusted. That is
the one failure this product cannot survive.

If a change makes that non-zero, it is not a tradeoff to weigh. Something is
wrong. Fix it or revert it.

There is also:

```bash
PYTHONIOENCODING=utf-8 python eval/adversarial_audit.py
```

which actively tries to construct bills that produce a false red. Both scripts
exit non-zero on failure, so either can gate a build.

For the frontend specifically:

```bash
cd frontend && npm run build && npm test && npm run lint
```

---

## Logging what you changed

Copy [`CHANGES_TEMPLATE.md`](CHANGES_TEMPLATE.md) to `CHANGES_BY_<yourname>.md`
and append as you go, not at the end — the reasoning is the part that gets
lost.

Two things worth writing down every time:

- **Decisions that could reasonably have gone the other way.** "Renamed the
  button" needs one line. "Merged two gray groups because a patient cannot act
  on the distinction" needs the reasoning, because someone may disagree and
  will need to know what was traded away.
- **What you tried that did not work.** A dead end you document saves the next
  person from walking down it.

---

## Where the rest is

- [`DECISIONS.md`](DECISIONS.md) — every ruling that should not be
  re-litigated, with the measurement behind it. Short, and worth reading
  before any non-obvious change.
- [`LIMITS.md`](LIMITS.md) — what the tool cannot do, and why.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how a bill becomes a report.

**One habit worth copying: measure before you conclude.** These notes have
been confidently wrong about what was broken, and each time a five-minute
script settled it. If you are about to act on something a document asserts,
check whether it is still true first.
