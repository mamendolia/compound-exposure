# compound-exposure

A data-driven method for prioritising security awareness work by combining a
**human risk vector** with a **technical risk vector** into a single ranking of
business units — the Compound Exposure Score the repository is named after — plus a working implementation that produces a directional
report from either synthetic or real data.

The problem it addresses is narrow and common. Most awareness programmes are
deployed uniformly across a workforce, report attendance rather than behaviour,
and cannot answer whether anything changed. This method spends the budget where
the measurement says the exposure is, and states plainly what the measurement
cannot support.

## Run it

Python 3.9 or later. **No third-party packages, no virtual environment, no
installation step** — the tools use only the standard library.

The interpreter is invoked differently by platform, which is the first thing
that trips people up:

| Platform | Command |
|----------|---------|
| Linux, macOS | `python3` |
| Windows | `py` (or `python`) — `python3` is intercepted by the Microsoft Store alias and will fail |

The commands below use `python3`. On Windows, substitute `py`.

```bash
# period 1 — baseline
python3 tools/generate_synthetic_data.py --users 2000 --period P1 --outdir data/synthetic
python3 tools/compute_exposure.py --indir data/synthetic --out data/scores.json
python3 tools/build_report.py --scores data/scores.json --out examples/sample-report.md

# period 2 — after intervention
python3 tools/generate_synthetic_data.py --users 2000 --period P2 --outdir data/synthetic-p2
python3 tools/compute_exposure.py --indir data/synthetic-p2 --out data/scores-p2.json

# did anything actually change?
python3 tools/compare_periods.py
```

The seed is fixed, so every clone produces byte-identical output. That
reproducibility is how you can tell the data is synthetic — a disclaimer in a
README proves nothing, a fixed seed proves it.

Results: [`examples/sample-report.md`](examples/sample-report.md) — where the
exposure is; [`examples/sample-change-analysis.md`](examples/sample-change-analysis.md)
— whether anything changed.

## The method in six steps

1. **Attribute** every person and every asset to a business unit, and record
   what could not be attributed instead of hiding it.
2. **Measure the human vector** — susceptibility, resilience, knowledge gap —
   over the enrolled population only.
3. **Measure the technical vector** — criticality-weighted severity over the
   worst asset quartile, plus remediation latency.
4. **Combine** the two into a compound exposure score using a geometric mean,
   so that only units exposed on both vectors rank at the top.
5. **Correct for data confidence**, inflating the score where coverage is thin,
   so that unmeasured populations cannot pass as safe ones.
6. **Segment** the prioritised units, matching the intervention — and the
   lure family used to test it — to what that unit's work actually looks like.
   A function that approves invoices by email does not have the same exposure
   as one that never handles payments.
7. **Recommend**, with a declared verification criterion attached to every
   recommendation.
8. **Measure the change** at the next period on a closed cohort, against a
   control arm, so the answer to "did it work" is evidence rather than
   assertion.

## Three design decisions worth arguing about

**Reporting rate carries the same weight as click rate, with the opposite
sign.** A click creates an incident someone has to discover; a report creates
an incident that has already been discovered. Two units clicking at the same
rate are not in the same position if one reports at 30% and the other at 3%.
Most reporting treats the phish-prone rate as the headline and reporting as a
nicety, and that ordering is backwards. See
[`docs/02`](docs/02-normalization-and-scoring.md).

**Attribution requires a control arm, and you get one without withholding
training.** Comparing two aggregate click rates cannot distinguish a working
programme from an easier campaign or from staff turnover. The fix is a
staggered rollout: every unit is trained, in the order the exposure ranking
already dictates, and the units scheduled later serve as the counterfactual for
the ones trained earlier. In the worked example this matters — one unit shows a
statistically significant improvement that disappears entirely once the control
arm is accounted for. See [`docs/06`](docs/06-measuring-change.md).

**Missing data raises the score, never lowers it.** A unit that is not measured
is not a unit with a clean record. The correction is a deliberate bias — it is
meant to make removing an awkward population from scope unattractive — and it
is disclosed rather than buried. See [`docs/05`](docs/05-limits.md).

## Running it on real data

The synthetic dataset demonstrates the method; a real engagement needs an
ingestion step, because the export never contains what the model assumes.

```bash
export EXPOSURE_SALT="a value you keep out of the repository"

python3 tools/make_example_export.py          # builds a KnowBe4-shaped fixture
python3 tools/ingest_knowbe4.py \
    --phishing examples/knowbe4-export-sample.csv \
    --roster examples/roster-sample.csv \
    --mapping mappings/example-client.json \
    --outdir data/ingested --period P1
```

Three things the ingestion enforces, each of which is a way real data lies:

**A roster is required.** A phishing export contains only enrolled people —
someone never enrolled is absent, not zero. Without an authoritative headcount
there is no denominator, and coverage confidence cannot be computed at all.

**Delivery, not scheduling, is the denominator.** Bounced messages are excluded.
Counting them as unclicked sends deflates the failure rate, always in the
flattering direction.

**Failure is graded.** A click, an opened attachment, an enabled macro and a
submitted credential are all failures and are not the same failure. Each
delivered message is scored by the worst action recorded against it.

The tool prints exclusion counts, per-unit coverage, and a warning when people
appear under more than one unit value — which usually means the chosen column
is a campaign targeting group rather than an org unit, and attribution is
circular. Read that output before trusting any score. Details in
[`docs/07`](docs/07-ingesting-real-data.md).

Per-client mapping files and raw exports are gitignored. Email addresses are
hashed with a salt supplied through the environment; the tool refuses to run
without one.

## Repository layout

```
docs/
  01-data-model.md                 Sources, fields, the mapping layer, personal data handling
  02-normalization-and-scoring.md  Formulas, weights, and why each one is what it is
  03-segmentation-and-indicators.md The indicator hierarchy and how to segment a prioritised unit
  04-nis2-article-20.md            What this evidences under NIS2, and what it does not
  05-limits.md                     Known failure modes, including the unsolved ones
  06-measuring-change.md           Longitudinal method: cohorts, control arms, what noise looks like
  07-ingesting-real-data.md        Running it on an actual export: rosters, graded failure, attribution traps
tools/
  generate_synthetic_data.py       Fixed-seed dataset with deliberately heterogeneous units
  compute_exposure.py              HRI, TRI, CES, coverage confidence
  build_report.py                  Scores to a directional report
  compare_periods.py               Period-over-period change with attribution testing
  ingest_knowbe4.py                Raw phishing export to model format, with pseudonymisation
  make_example_export.py           Builds an export-shaped fixture from the synthetic data
mappings/
  example-client.json              Column mapping template; per-client copies are gitignored
templates/
  human-risk-reduction-report.md   The report structure, empty
examples/
  sample-report.md                 Single-period output, regenerable from the commands above
  sample-change-analysis.md        Period-over-period output, with attribution
  knowbe4-export-sample.csv        Fixture in the shape of a real export (invented)
  roster-sample.csv                Fixture headcount list (invented)
```

## Scope and honesty notes

- **All data in this repository is invented.** No client engagement, dataset or
  finding is reflected here in any form, anonymised or otherwise.
- **The weights are argued, not fitted.** There is no training set and no
  empirical calibration. Presenting this as a validated model would
  misrepresent it.
- **The score orders work.** It is not a measurement of risk in any external
  unit, it does not convert to money, and it does not support benchmarking
  between organisations.
- **Blast radius is not modelled**, which means the lowest-ranked unit in the
  sample output is also the one whose compromise would matter most. That is a
  known limit, discussed in `docs/05`, not an oversight.

## Intellectual debts

The two-vector framing owes its shape to Roger Grimes's data-driven defence
argument — that most security effort is spent disproportionately to how
attacks actually succeed. The knowledge–behaviour distinction that keeps
training completion weighted low draws on Perry Carpenter's work on why
knowing and doing come apart under pressure, and on the Carpenter/Roer security
culture dimensions. The treatment of susceptibility as a property of the lure
rather than of the person draws on Luca Allodi's empirical work on cognition in
social engineering.

None of these authors is responsible for what has been done with their ideas
here.

## Licence

MIT. See [`LICENSE`](LICENSE).

*Italian summary: [`README.it.md`](README.it.md)*
