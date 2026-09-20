# BillWise — cue card

Keep this open while recording. Glance, don't read.
**A** and **B** = the two of you. Roughly 5–6 minutes.

---

### 1 · PROBLEM — 40s · *landing page*

**A** — Family member's hospital bill. No idea if the numbers were fair.
**A** — Government publishes a maximum price for many medicines. 915 of them.
**A** — But it's a spreadsheet. Nobody looks it up at a counter.
**B** — So: photograph your bill, we check it against that list.

> lost? **"The price list exists. Nobody can use it. We made it usable."**

---

### 2 · DEMO — 90s · *Try a sample bill*

**A** — Uploading a hospital bill… two things are reading it at once.
**B** — Headline: *"we compared 4 of the 16 charges."* That number matters.
**A** — Bare Metal Stent → ₹24,500.
**B** — **Show evidence** → the ceiling, the GST, the subtraction, the
government order number and date.
**A** — You're not saying "this is wrong". You're saying "here's the
notification, help me understand this line."

> lost? **"Every number here comes from the government's own list."**

---

### 3 · THE GREY ONE — 90s · *second sample, retail pharmacy*

**B** — Couldn't check a single line on this bill. And it says so.
**B** — Not "looks fine". *"We could not compare any of these — this does not
mean the bill is fine."*
**A** — Sounds like failure. It's the whole point.
**A** — Easy version finds nothing and tells you you're fine. You walk away
reassured about a bill nobody checked.
**B** — We had that bug. "Zero things worth asking about" on a bill we'd
checked nothing on. Every word true, whole screen a lie.
**A** — Now the first number is always **how many we checked**, not how many
problems we found.
**B** — Groups below say *why* each line wasn't checked. Not price-controlled
is the law, not our failure. Couldn't identify is different. We say which.

> lost? **"It's only useful if it can say 'I don't know'. Ours says it a lot."**

---

### 4 · UNDER THE HOOD — 90s

**B** — Goes to AWS. Two models read it: **Textract** + **Nova**. Separately.
**A** — They agree → we trust the line. They disagree → grey, thrown out.
**B** — One model alone once reported 97% confidence on a line it had read
completely wrong. Shifted a whole column.
**A** — **"A single reader can't doubt itself."** Second model isn't there to
be smarter — it's there to disagree.
**B** — And: **the AI never decides anything.** It reads. That's it.
**B** — Every calculation and verdict is plain Python. Rules we wrote.
**A** — If a language model does your arithmetic you can't explain the answer.
For questioning a hospital bill, you have to be able to explain it.

> lost? **"Two AIs read it. Regular code decides. The AI never does maths."**

---

### 5 · PROOF — 45s · *terminal / eval output*

**A** — How do we know it isn't confidently wrong?
**B** — Test bills where we planted the problems. Finds **46 of 46**.
**B** — The number we care about: **zero false alarms.** Never flagged a
correctly-billed line.
**A** — And we tried to break it. Built bills designed to trick it. **10
attempts, none worked.**
**B** — Being wrong *that* direction — telling someone they were overcharged
when they weren't — you don't recover from that.

> lost? **"46 of 46 found. Zero false alarms. 10 attacks, none worked."**

---

### 6 · LIMITS — 40s

**B** — English / Latin script only. Hindi or Marathi bill won't work.
Reading isn't the blocker — our medicine database is in English so the name
matches nothing.
**A** — Photos under 4 MB. Most phone cameras are bigger. You shrink it first.
We know.
**B** — Only the 915 medicines the government price-controls. Yours might not
be on it — we'll say it isn't price-controlled. True, honest, not the answer
you wanted.
**A** — We'd rather say that than make something up.

> lost? **"English only. Small photos. Only what's actually price-controlled."**

---

### 7 · CLOSE — 25s · *landing page*

**A** — It's live. Lambda, Textract, Bedrock, Amplify. Use it now.
**B** — We didn't set out to catch hospitals. Most bills are fine. We wanted a
patient to be able to ask a question with something solid behind it.
**A** — Thanks for watching.

---

## ALWAYS / NEVER

**Say:** may need clarification · above the listed ceiling · worth asking
about · we couldn't check this

**Never:** illegal · fraud · cheating · overcharged · scam · caught them

## Safe numbers

915 ceilings · 46/46 found, 0 missed · **0 false alarms** · 0 of 10 attacks ·
298 tests · two readers live in production

**No accuracy percentage.** If pushed: *"Good on clean documents, poor on bad
photos — and when it isn't sure it says so instead of guessing."*

## If it breaks on camera

*"Real upload, real server, sometimes slow — here's one we ran earlier."*
Cut to recording. Don't debug live.
