# Clarification letter

Generate a polite request for an itemised explanation of specific charges.

## Hard rules

1. **Never** the words illegal, fraud, cheating, overcharged, scam. Use
   "above the listed ceiling price", "may need clarification",
   "amount affected".
2. **No legal threats.** No mention of courts, complaints, regulators,
   consumer forums or penalties. This is a request for information.
3. **No demand for money.** Ask for an explanation, not a refund.
4. **Introduce no number that is not in the supplied evidence.** Every rupee
   figure, ceiling, S.O. number and date comes from the flags.
5. Cite the S.O. number and date for every price point raised.
6. Say plainly that the sender may have misread the bill and welcomes
   correction. They might have.

## Input

A list of flags with their evidence, and the bill's identifying details.

## Output

Plain text. A short greeting, one paragraph of context, a numbered list of
the points, a closing line. Under 300 words.

The local-mode template in `backend/app/pipeline/letter.py` is the reference
implementation. A model version must not exceed what it claims.
