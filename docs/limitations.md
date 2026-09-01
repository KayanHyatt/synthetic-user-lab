# Limitations

This project's synthetic panel does not replace real user research (see
`README.md`). This file states, from `docs/validity_report.md`'s measured
results, where the panel is useful, where it is not, and what it
systematically misses.

## Where the panel is useful

Reproducibility is real and measured: the same seed, run again, produces the same finding count and the same top-5 cluster membership every time (variance 0.0, mean top-5 Jaccard overlap 1.0). Any disagreement between two runs of the same study configuration is a real signal worth investigating, not measurement noise from the harness itself.

## Where it is not, and what it systematically misses

### 1. Cluster themes partly reflect the Analyst's writing style, not just panel agreement

Near-duplicate paraphrases of one problem cluster at a maximum internal cosine distance of 0.448; distinct problems phrased in the same uniform "Analyst voice" sit as close as 0.645 apart. The margin between them (0.197, against a `distance_threshold` of 0.6) is real but not large: TF-IDF cosine similarity over Analyst-authored summaries partly measures how uniformly the Analyst writes, not how much the underlying panel actually agrees. A study whose Analyst calls happen to use more uniform phrasing will show tighter, larger clusters than one whose calls don't, independent of what the personas actually reported.

### 2. A rare theme and a broken measurement look identical in the report

Of 2 singleton clusters in a targeted fixture, 1 came from a finding whose summary vectorised to an all-zero TF-IDF row (short or generic enough that every token was excluded before clustering even started), and 1 were genuine frequency-1 themes. Nothing in a rendered report tells them apart -- a reader sees "1 persona reported this" either way, whether that means a real, rare finding or a finding the clustering pipeline never had a chance to place.

### 3. Cluster granularity at a fixed threshold is unmeasured territory as studies scale up

At `distance_threshold=0.6` (the shipped default, unchanged here), cluster count and mean cluster size across increasing synthetic corpus sizes:

| Finding count | Cluster count | Mean cluster size |
|---|---|---|
| 10 | 3 | 3.33 |
| 25 | 5 | 5.00 |
| 50 | 8 | 6.25 |
| 100 | 8 | 12.50 |

This threshold was calibrated against a seven-document fixture (§M5); this table is the first measurement of its behaviour at larger, more realistic finding counts. The default is unchanged here -- `distance_threshold` and `sklearn.__version__` are embedded in every report's provenance, and changing the default would break comparability with every report already produced.

## The four provider-gated checks, in full when a real provider measured them

Discriminative validity, acquiescence bias, position bias, and known-answer calibration all depend on the panel's output actually reflecting the artefact, the question framing, or the option position it was given -- so none of them is offline-measurable by construction, and each is not counted toward the two measured weaknesses above. That is a statement about *what this file's own acceptance criterion counts*, not a reason to leave the numbers out of this file when they exist: relegating a check as serious as acquiescence bias to `docs/validity_report.md` alone, while this file's own opening line reads as a finished account of the panel's limits, is the same overclaim as not measuring it at all. Whenever `sul validate` had a real (or cassette-backed) provider available for a check below, its numbers -- with their denominators -- are printed here directly.

### Discriminative validity

- Bad artefact blocker/confusion count: 6 (5/5 personas)
  - Category breakdown: blocker: 1, confusion: 5, missing_info: 2
  - Distinct evidence anchors (turn ordinal, category): 5
- Good artefact blocker/confusion count: 0 (5/5 personas)
  - Category breakdown: delight: 2
  - Distinct evidence anchors (turn ordinal, category): 1
- Material difference: True

### Acquiescence bias

- Positively framed question: Was the pricing clear?
- Negatively framed question: Was anything unclear about the pricing?
- Positive-framing agree rate: 0.0
- Negative-framing agree rate: 1.0
- Agreement gap: 1.0 (5/5 subjects) -- the panel agreed with whichever framing it was given, at this gap, over this denominator

### Position bias

- Options: ('Starter plan: $15/mo billed annually, 1 seat', 'Team plan: $49/mo per workspace, up to 10 seats')
- First-position share (original order): 1.0
- First-position share (reversed order): 1.0
- Preference shift: 0.0 (5/5 subjects)

### Known-answer calibration

- Detected: 1 / 3 (5/5 bad-artefact personas)
- Detection rate: 0.3333333333333333

## These numbers describe one specific model configuration

`sul validate` picked up a real, cassette-backed recording for this run (PROJECT_SPEC.md §M6 Deviation 5, amended) rather than falling back to `FakeProvider` -- `tests/cassettes/` had traffic to replay. See the **Provenance** rows in `docs/validity_report.md` for exactly which model served each agent role (persona, moderator, analyst, probes) for each check.

**Those numbers describe that one configuration and do not transfer down a model tier.** A different Analyst model, or a different persona/moderator model, is a different measurement, not an extrapolation from this one -- nothing here should be read as validating a cheaper or different model combination than the Provenance rows actually show. One such swap has actually been measured, on this one 5-persona panel, one seed, one artefact pair: replaying the identical bad-artefact transcripts through a Haiku Analyst instead of Sonnet left the blocker/confusion aggregate and the material-difference verdict unchanged (6 vs 0 either way) but not what produced it -- zero `blocker` findings where Sonnet registered one, evidence anchored to 2 distinct transcript positions where Sonnet anchored to 5, severities skewed lower, at roughly a quarter the Analyst spend (`tests/test_validity_cassette_report_determinism.py::test_config_b_numbers_are_reproducible_and_complete`) -- so on this transcript, this run, the headline metric did not register a real, material change in what the Analyst actually found, which is a property of this run, not a general claim about either model. See PROJECT_SPEC.md's §M6 Deviation 18-20 for what was recorded, what failed along the way, and what (if anything) remains open.
