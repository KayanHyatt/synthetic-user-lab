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

## These numbers describe one specific model configuration

`sul validate` picked up a real, cassette-backed recording for this run (PROJECT_SPEC.md §M6 Deviation 5, amended) rather than falling back to `FakeProvider` -- `tests/cassettes/` had traffic to replay. See the **Provenance** rows in `docs/validity_report.md` for exactly which model served each agent role (persona, moderator, analyst, probes) for each check.

**Those numbers describe that one configuration and do not transfer down a model tier.** A different Analyst model, or a different persona/moderator model, is a different measurement, not an extrapolation from this one -- nothing here should be read as validating a cheaper or different model combination than the Provenance rows actually show. See PROJECT_SPEC.md's §M6 Deviation 12/13 for what was recorded, what failed along the way, and what (if anything) remains open.
