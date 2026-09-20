# BillWise — 3-minute script (tech, architecture, AWS, what we learned)

Two speakers, **A** and **B**. Target **3:00**. Measured at **468 spoken words = 2:56** at a normal 160 wpm,
so it fits with a little room. The per-section seconds below are MEASURED from
the word counts, not estimated.

This is the TECHNICAL cut. The demo-led 5–6 minute version is
`docs/VIDEO_SCRIPT.md`; the cue card for it is `docs/VIDEO_CUECARD.md`.

Screen: site for section 1, architecture slide for 2–3, terminal for 4.

Every number here was verified on 2026-09-20. Do not add one that was not.

---

## 1 · WHAT IT IS — 20s · *the live site*

**A:**
"In India the government publishes a maximum legal price for about nine
hundred medicines. It's public. It's also a spreadsheet nobody reads at a
pharmacy counter."

**B:**
"BillWise takes a photo of your bill and checks it against that list — and
shows you the arithmetic and the government order number behind every line."

> **Stuck?** *"The price list exists. Nobody can use it. We made it usable."*

---

## 2 · THE STACK — 37s · *architecture slide*

**B:**
"It's serverless, end to end, in one AWS region."

"The bill hits **API Gateway**, lands in **S3** encrypted, and a **Lambda**
running FastAPI does the work. Results go to **DynamoDB**. The frontend is
React on **Amplify**."

**A:**
"The reading is two services, not one. **Textract** pulls the line items, and
**Amazon Nova** through **Bedrock** reads the same bill independently."

**B:**
"And then the important bit — **the AI never decides anything.** It reads.
Every comparison, every calculation, every verdict is plain Python we wrote.
Because if a language model does your arithmetic, you can't explain the answer
to a hospital."

> **Stuck?** *"Two AWS services read it. Regular code decides. The AI never
> does maths."*

---

## 3 · WHY TWO READERS — 42s

**A:**
"The second reader isn't there to be more accurate. It's there to **disagree**."

**B:**
"We proved that by accident. The same bill, the same deployed system, two
hours apart — one variable changed. With one reader, four of seven lines came
back high confidence, and it produced a finding that was **wrong**. With two
readers, zero of seven, and no finding at all."

**A:**
"Textract reported ninety-six to ninety-nine percent confidence *both* times.
**Confidence is not accuracy, and a single reader can't doubt itself.**"

**B:**
"So when they disagree, we go grey and say so. Forty-six out of forty-six
planted problems found, and **zero false alarms** — including ten bills we
built specifically to trick it."

> **Stuck?** *"The second model exists to disagree. Silence beats a wrong
> accusation."*

---

## 4 · WHAT AWS TAUGHT US — 61s · *terminal*

**A:**
"Two AWS errors cost us hours. And one decision saved us."

**B:**
"First — we moved the whole stack to Mumbai to sit near Indian users, then
moved it back. The error said the model wasn't available in that region. It
actually meant **our account wasn't approved anywhere yet.** Those look
identical in the console."

**A:**
"Second — our model's Marketplace offer expired mid-project. It surfaced as a
permissions error on the Lambda role. We spent an hour on IAM for something
IAM could never have fixed."

**B:**
"And the decision — our reader uses
Bedrock's **Converse** API, which is model-agnostic. So swapping models was a
**config change, not a code change.** That design decision paid for itself the
day the offer expired."

**A:**
"And one we'd defend in review: we pin the inference profile to **three named
regions** in IAM. The global one routes to thirty-three. For somebody's
medical bill, that IAM policy *is* the data-residency control."

> **Stuck?** *"Two of our biggest bugs weren't bugs. They were AWS telling us
> something in a confusing way."*

---

## 5 · CLOSE — 16s

**B:**
"Two hundred and ninety-eight tests, zero false alarms, running live on AWS."

**A:**
"We didn't build this to catch hospitals. Most bills are fine. We built it so
a patient can ask one informed question — with the government's own number
behind it."

---

## Numbers you can defend

- **915** ceiling-price formulations, NPPA's published list
- **46 of 46** planted problems found, **0 missed**
- **0 false alarms**, and **0 of 10** deliberate attempts to cause one
- **298** automated tests
- Two readers, cross-checking, **live in production**

**Do not claim a reading-accuracy percentage.** We don't have one we trust. If
pushed: *"Good on clean documents, poor on bad photos — and when it isn't sure
it says so instead of guessing."*

**Never say:** illegal · fraud · cheating · overcharged.

## If you overrun

Cut section 3 down to the two bold lines — "the second reader exists to
disagree" and "confidence is not accuracy" — and drop the 0-of-7 / 4-of-7
figures. That saves about 20 seconds and loses the least.
