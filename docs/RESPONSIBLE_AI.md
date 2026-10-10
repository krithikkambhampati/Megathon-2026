# Responsible AI note

How the Green Home Score & Retrofit Engine handles privacy, bias, explainability, hallucination, human
oversight and data limitations (Problem Statement 2, deliverable H). Details are in the linked documents.

LLM results come from `reports/llm_eval.md` (80 test scenarios). The app uses the open-weight
`gpt-oss-120b` hosted on Groq; only the fact sheet of computed numbers is sent, never an address or personal details. The unsupported-claim rate is **pending** the human annotation of 40 answers.

## 1. Privacy

- **No personal or confidential data.** The datasets are public: EPC certificates, HM Land Registry Price Paid,
  UK HPI, NEED, DESNZ conversion factors, Met Office and PVGIS ([DATA.md](DATA.md) §2).
- **Addresses never leave the build step.** EPC and Land Registry addresses (© Royal Mail/OS) are used only to
  join sales to certificates in `data/interim/`. They are dropped before anything is written to
  `data/processed/`, and real EPC keys are replaced by synthetic property ids.
- **Customers are synthetic.** Who owns which property is generated, never taken from real data.
- **The app never asks for an address or a name.** It asks about the home's features and energy use only.
- **Everything runs locally.** The engine, the models and the language model (Ollama) run on one laptop, so
  no answers leave the machine. If a hosted OpenAI-compatible model is configured instead, the fact sheet for
  an answer (the home's computed results, no identifiers) is sent to that provider; the key lives in `.env`.
- **Nothing about a user is stored.** Analyses are kept only in an in-memory cache that is cleared when the
  API restarts.

## 2. Bias and coverage

| Source of bias | Effect | How we handle it |
|---|---|---|
| EPCs exist only where a home was sold, let or built | Homes that never change hands are under-represented | Stated in the data documentation; scores apply to any home but models learned from EPC'd homes |
| City-heavy sample (11 local authorities; 34% flats vs ≈22% nationally) | Flat and urban patterns weigh more | Rating mix checked against national NEED (within ~4 points); peer comparisons are banded by size and type |
| Off-gas homes (oil, LPG, solid fuel, community heating; ≈9%) are excluded from savings | Mostly rural homes get a score but no savings estimate | The app says so explicitly ("savings are only modelled for mains gas or electricity") instead of guessing |
| England and Wales only | Not valid for Scotland or Northern Ireland | Stated as a limitation |
| EPC assessors never recommend heat pumps in this data (before RdSAP 10) | The recommender has little evidence for heat pumps | Heat-pump relevance is learned from 2025+ certificates only; feasibility rules, not the model, decide what is possible |
| SAP is cost-based | A heat pump replacing a modern gas boiler moves the rating little | Monotone constraints guarantee a better state never lowers the predicted rating ([MODELS.md](MODELS.md)) |
| Large homes use more energy in total | Size could be mistaken for inefficiency | The score uses energy per m², and peers are compared within the same size band |

## 3. Explainability

- **The score is a formula, not a model.** Seven fixed weights times documented sub-score tables
  ([SCORING.md](SCORING.md)). The Score screen shows each component's contribution, the sub-score tables
  ("How is this computed?") and the score after the recommended package.
- **Unknown answers are visible.** "Not sure" stays unknown; estimated values are labelled "Estimated by a
  model" or "Assumed", and the score shows a range when unknowns could change it.
- **Every recommendation gives its reasons** in plain English (for example "Works best after insulating the
  home first"), its suitability, savings per fuel and cost range. Retrofits that don't suit the home are
  listed with the reason.
- **Data problems are shown, not hidden.** Missing months, conflicting answers and outliers appear as notes
  with a message (for example "Monthly gas readings cover part of the year; the annual figure is scaled up").
- **The models are documented with their baselines,** design decisions and monotone constraints
  ([MODELS.md](MODELS.md)); `/v1/methodology` exposes the weights, tables, catalogue and emission factors.

## 4. Hallucination

A local language model will sometimes invent or round numbers, so it is never trusted with one.

- It receives a **fact sheet** of numbers already computed by the engine and formatted exactly as the screens
  show them, and is told to copy them and do no arithmetic.
- Every reply goes through a deterministic **number checker**:
  - every number must match a fact;
  - money claims the tool has no figure for (bill savings, £ value gains) fail;
  - "guarantee"-style promises and mortgage advice fail;
  - an increase described as a saving (for example a heat pump's extra electricity) fails.
- A failed reply is **retried once** with the problems listed, then replaced by a **template answer** built
  from the same facts. The user never sees an unchecked number, and each answer shows whether it was
  verified or is a template answer.
- **What-if questions rerun the models first**; the language model only explains the new results.
  Infeasible requests are refused with the engine's reason.
- The whole answer has a **25-second budget**; after that the template answer is used, so a slow model never
  blocks the app. The app works with the language model off.

Measured effect (80 scenarios): numeric groundedness **84.3%** in the model's raw first drafts and **100%**
in the answers shown, with **100%** of shown numbers matching a fact (targets ≥ 90%). The checker's most
frequent catch was an electricity increase after a heat pump described as a saving. Still open: answers
mention required data notes and reasons only 63.5% of the time (target 90%; the template always includes
them), and one of 80 answers contained a wrong non-numeric statement. The human-annotated unsupported-claim
rate (two independent annotators, target < 5%) is pending.
Details: [LLM.md](LLM.md), `reports/llm_eval.md`.

## 5. Human oversight

- **Estimates, not advice.** Savings and carbon are labelled "estimates, not guarantees"; property value
  changes are "indicative, not causal". The tool gives no financial or mortgage advice.
- **Surveys for uncertain cases.** Retrofits whose suitability depends on unknown answers are marked "Needs a
  survey" rather than recommended outright.
- **Feasibility is rule-based.** Whether a retrofit is physically possible (for example no loft insulation
  under another flat) is decided by documented rules, never by a model.
- **The user stays in control of scenarios.** What-if results are shown next to the recommended plan, so the
  user sees what each choice changes.

## 6. Data limitations

- **Synthetic parts.** No public source gives monthly metered energy per home or post-retrofit outcomes, so
  these are generated: monthly energy is calibrated to NEED medians and band shapes (spread ≈74–84% of real
  data), and post-retrofit energy comes from a physics simulator with hidden household factors. Agreement with
  synthetic targets does not establish real-world accuracy; where real evidence exists we compare with it
  (NEED observed savings, repeat-EPC rating changes, real sale prices) ([DATA.md](DATA.md) §1).
- **Labels are noisy.** 23% of repeat-certificate pairs were discarded as inconsistent; solar, cavity and solid
  wall are recommended in 95–97% of feasible cases, which carries little information.
- **Estimated inputs.** Bedrooms are estimated from habitable rooms and floor area; unknown answers are filled
  from training-data tables and flagged.
- **Unknown answers in training vs the app.** The simulator labels treat unknown inputs as infeasible, while
  the app offers such retrofits as "needs survey". For homes with all answers known the rules agree exactly.
- **Property value is associational.** A hedonic model on real sales gives an indicative range from 20
  bootstrap members; location is region-level. It does not prove that a retrofit causes a price rise.
- **Leakage controls.** Splits are by customer; bounds, calibration and peer percentiles use the training
  split only; rating-at-sale never uses a later certificate ([DATA.md](DATA.md) §7).
