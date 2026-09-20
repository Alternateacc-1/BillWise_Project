# BillWise — full video script

Two speakers. **A** and **B** — swap in your names. Target **5–6 minutes**.

Screen is on the website the whole time except where it says otherwise.
Nobody reads this out word for word. It is here so that if you lose your
thread, you glance down, find the bold line, and carry on.

---

## SECTION 1 — The problem (about 40 seconds)

**Screen:** the landing page, not scrolling. Just sitting there.

**A:**
"Last month a family member of mine got a hospital bill. Eleven lines on it.
And we had no idea whether any of those numbers were fair."

"Here's the thing — for a lot of medicines in India, there *is* an official
maximum price. The government publishes it. It's called the ceiling price,
and no hospital or pharmacy can charge above it."

"But it's a spreadsheet. Nine hundred and fifteen rows. Nobody standing at a
pharmacy counter is going to look that up."

**B:**
"So that's what we built. You photograph your bill, and it tells you which
lines have a published price limit, and whether you were charged inside it."

> **Stuck?** The one line that matters: *"The price list exists. Nobody can
> use it. We made it usable."*

---

## SECTION 2 — The demo (about 90 seconds)

**Screen:** click **Upload a bill** → **Try a sample bill**. Let it run.

**A:**
"So I'll upload a hospital bill here… and give it a few seconds."

*(while it loads)*

"Behind this, two things are reading the bill at the same time. We'll come
back to why there are two."

**Screen:** the report appears.

**B:**
"Okay. So first thing it says — *we compared four of the sixteen charges.*"

"That number matters more than it looks. We'll come back to it."

**Screen:** scroll to **What we found**. Click into the **Bare Metal Stent**.

**A:**
"Here's a stent, billed at twenty-four and a half thousand rupees."

**Screen:** click **Show evidence**.

**B:**
"And this is the part we care about most. It's not just saying 'this looks
high'. It shows you the published ceiling. It shows the GST added on top. It
shows the subtraction. And it gives you the government order number and the
date it was published."

**A:**
"So if you take this to the hospital, you're not saying 'I think this is
wrong.' You're saying 'here's the notification, can you help me understand
this line.' That's a completely different conversation."

> **Stuck?** Just point at the evidence panel and say: *"Every number here
> comes from the government's own list. We don't estimate anything."*

---

## SECTION 3 — The part we're actually proud of (about 90 seconds)

**Screen:** go back, load the second sample — the retail pharmacy one.

**A:**
"Now I want to show you the opposite. Because this is the bit that took us
the longest."

**Screen:** the report loads. Headline reads *"We could not compare any of the
six charges on this bill."*

**B:**
"This bill — we couldn't check a single line on it. And it says so."

"It doesn't say 'looks fine'. It doesn't show a green tick. It says: we could
not compare any of these, and this does not mean the bill is fine."

**A:**
"That sounds like a failure. It's actually the whole point."

"Think about what the easy version of this app does. It finds nothing, and it
tells you you're fine. And you walk away reassured about a bill nobody
checked."

**B:**
"We had that bug. Genuinely. It said 'zero things worth asking about' on a
bill where we'd checked *nothing*. Every word was true and the whole screen
was a lie."

**A:**
"So now the first number you see is always how many we actually checked. Not
how many problems we found."

**Screen:** scroll to the grey groups.

**B:**
"And down here it tells you *why* each line wasn't checked. Some of these
medicines just aren't price-controlled in India — that's not our failure,
that's the law. Others we couldn't identify. Those are different things and
we say which."

> **Stuck?** *"A tool like this is only useful if it's willing to say 'I don't
> know'. Ours says it a lot."*

---

## SECTION 4 — What's happening underneath (about 90 seconds)

**Screen:** whatever you like here — architecture slide, or stay on the site.

**B:**
"Quick version of what's actually running."

"The bill goes to AWS. Two different AI models read it — Textract, which is
Amazon's document reader, and Nova, which is a vision model. They read the
same bill separately."

**A:**
"And then we compare what they said. If they agree on a line, we trust it. If
they disagree — different name, different amount, anything — we throw that
line out and mark it grey."

**B:**
"We learned that the hard way. At one point only one model was running, and it
reported a line at ninety-seven percent confidence. It was wrong. Completely
wrong — it had shifted a whole column."

**A:**
"A single reader can't doubt itself. That's the phrase that stuck with us.
The second model isn't there to be smarter. It's there to disagree."

**B:**
"And then the important bit — **the AI never decides anything.**"

"It reads. That's all it does. Every calculation, every comparison against
the ceiling, every verdict — that's plain Python. Rules we wrote, that we can
read, that run the same way every time."

**A:**
"Because if a language model does your arithmetic, you can't ever fully
explain why it said what it said. And for something that questions a
hospital's bill, you need to be able to explain it."

> **Stuck?** *"Two AIs read it. Regular code decides. The AI never does
> maths."*

---

## SECTION 5 — How we know it's safe (about 45 seconds)

**Screen:** terminal, run the eval. Or a still of the output.

**A:**
"So how do we know it's not just confidently wrong?"

**B:**
"We built a test set of bills where we already know the answers — we planted
the problems ourselves. It finds all forty-six of them."

"But the number we actually care about is the other one. **Zero false
alarms.** Not once has it flagged a line that was correctly billed."

**A:**
"And we went further — we tried to *break* it. We deliberately built bills
designed to trick it into a false accusation. Ten attempts. None of them
worked."

**B:**
"That's the number we'd put our name to. Because being wrong in this
direction — telling someone their pharmacy overcharged them when it didn't —
that's not a bug you recover from."

> **Stuck?** *"Forty-six out of forty-six found. Zero false alarms. Ten
> attempts to break it, none worked."*

---

## SECTION 6 — What it can't do (about 40 seconds)

**Screen:** back on the site, or just talking heads.

**A:**
"We should be straight about the limits, because there are real ones."

**B:**
"It only reads English and Latin script. A bill printed in Hindi or Marathi —
it can't do it yet. And that's obviously a problem for an Indian product. The
reading part isn't the blocker, it's that our medicine database is in
English, so the name wouldn't match anything."

**A:**
"Photos need to be under four megabytes, which most phone cameras exceed. You
have to shrink it first. We know. It's on the list."

**B:**
"And the big one — we can only check medicines that are on the government's
list. That's nine hundred and fifteen. There are a lot more medicines than
that in India. If yours isn't on it, we'll tell you it isn't price-controlled
— which is true and honest, but it isn't the answer you wanted."

**A:**
"We'd rather tell you that than make something up."

> **Stuck?** *"English only. Small photos only. And only the medicines the
> government actually price-controls."*

---

## SECTION 7 — Close (about 25 seconds)

**Screen:** landing page.

**A:**
"It's live. It's running on AWS — Lambda, Textract, Bedrock, Amplify — and
you can use it right now."

**B:**
"We didn't set out to catch hospitals doing something wrong. Most bills are
fine. We just wanted a patient to be able to ask a question with something
solid behind it."

**A:**
"That's it. Thanks for watching."

---

## Things to keep saying, and things never to say

**Say:** *may need clarification · above the listed ceiling · worth asking
about · we could not check this.*

**Never say:** *illegal · fraud · cheating · overcharged · scam · caught them.*

That isn't us being careful for the video. It's in the product too. We are
not accusing anybody — we're helping someone ask.

## Numbers you can defend if a judge pushes

- **915** ceiling-price formulations, from NPPA's published list
- **46 of 46** planted problems found, **0 missed**
- **0 false alarms**, and **0 of 10** deliberate attempts to cause one
- **298** automated tests
- Two readers, cross-checking, **running live in production**

**Do not claim a reading-accuracy percentage.** We don't have one we trust —
on a clear PDF it reads well, on a bad phone photo it often doesn't, and it
goes grey rather than guessing. If asked: *"On clean documents it's good. On
bad photos it isn't, and when it isn't sure it says so instead of guessing."*

## If something breaks live

Don't fight it. Say: *"That's a real upload hitting a real server, so
occasionally it's slow — here's one we ran earlier"* and cut to a recording.
Nobody minds. Trying to debug on camera is what kills a demo.
