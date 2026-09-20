# Change log — <your name>

Copy this file to `docs/CHANGES_BY_<yourname>.md` and append as you work.
Write entries AS YOU GO, not at the end: the reasoning is the part that gets
lost, and the reasoning is what the owner is reading this for.

---

## <date> — <short title>

**What I changed:** files touched, one line each.

**Why:** the problem being solved. If it was a judgement call, what the
alternatives were and why you rejected them.

**How I checked it:** what you ran or clicked, and what you saw.

**Anything I am unsure about:** what the owner should look at, or what you
would do differently with more time.

---

## Worth logging even though it feels unnecessary

- **A decision that could reasonably have gone the other way.** Renaming a
  button needs one line. Merging four result groups into two needs the
  reasoning, because the owner may disagree and has to know what was traded.
- **Anything you tried that did not work.** A documented dead end saves the
  next person from walking down it.
- **Anything you deleted.** Especially copy. Several sentences in this UI look
  redundant and are each a bug that reached a real user's screen -- see
  section 5 of `docs/FRONTEND_BRIEF.md`. Removing one may be right; it should
  be a decision, not a tidy-up.
- **Any run of the test or eval suites**, if you touched `backend/`. Paste the
  test count and the eval's caught / missed / FALSE REDS lines.
