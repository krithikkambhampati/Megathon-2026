# Annotation rubric: are the LLM's claims supported by its facts?

You get `RESPONSES.md` (40 answers, each with the FACTS and DATA_NOTES it was written from) and your own
`annotator_<you>.csv`. **Label on your own. Don't compare or discuss labels with the other annotator until
you have both sent your sheets in.** The two sheets list the same sentences in a different order on purpose.

## What to do for each row
1. Find the sentence in `RESPONSES.md` (by `sentence_id`, e.g. `R07.3`), and read its FACTS.
2. Split the sentence into **atomic claims**: single statements that could be true or false on their own.
   "Gas falls by 11,130 kWh/year while electricity rises by 1,240 kWh/year" = 2 claims.
3. Fill in:
   - `claims`: how many atomic claims the sentence makes (0 if none).
   - `unsupported_claims`: how many of them are NOT supported by the FACTS / DATA_NOTES / REASONS.
   - `label`: one of
     - `supported`: every claim is supported.
     - `partly`: some claims supported, some not.
     - `unsupported`: no claim is supported.
     - `not_a_claim`: no factual claim (greetings, "Shall I save these?", general caveats).
   - `comment`: optional, short. Say *why* for anything not `supported`.

## What counts as supported
- A number is supported only if it appears in FACTS (same value, allowing the displayed rounding).
  "about 11,100 kWh" for a fact of "11,130 kWh/year" is supported; "about 12,000" is not.
- Direction matters: a fact shown as "… increase" means use goes **up**. Calling it a saving is unsupported.
- A reason ("works best after insulating first", "there's another home above") is supported if it appears
  in REASONS or the fact labels.
- General safe wording ("these are estimates", "the value change is indicative, not guaranteed or
  causal", "a survey would confirm it") is `not_a_claim`, not unsupported.
- Advice the tool never gives (mortgages, loans, grants not in FACTS, bill savings in £) is unsupported.
- Anything about the home not in FACTS or DATA_NOTES (e.g. "your boiler is 15 years old") is unsupported.

## Examples
| Sentence | claims | unsupported | label |
|---|---|---|---|
| "Your score is 32 out of 100, which is Poor." (facts: 32, Poor) | 2 | 0 | supported |
| "A heat pump would save 3,600 kWh of electricity." (fact: 3,600 kWh/year increase) | 1 | 1 | unsupported |
| "Loft insulation is a cheap quick win and saves about £200 a year." (no £ saving fact) | 2 | 1 | partly |
| "These figures are estimates, not guarantees." | 0 | 0 | not_a_claim |

When done, save the CSV (keep the columns) and send it back. It takes about 40–60 minutes.
