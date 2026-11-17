# Inside the committee

This is a post-hoc audit of the original 360 saved agent executions. It changes
neither predictions nor financial scores. `protocol.json` defines membership,
candidate checks, review selection and limits. `observations.json`/`.csv` expose
one row per case × treatment × trial; `summaries.json`/`.csv` use those rows.

`reviews.json` contains five Codex assistant reviews with exact short excerpts,
source-field and prediction hashes, evidence digests and development regression
expectations. These are not human/domain-expert judgments. Full reports and
source-bearing traces remain in the private evidence project. The published
Forge internals dashboard provides authenticated conversation links.

The five reviews cover the original weakest example, both research-to-final
rating changes, the strongest default-committee directional example and the
original seed-2026 random committee example. They were selected after seeing
results and cannot be used as untouched test evidence.

Checks intentionally have narrow meanings:

- A conditional phrase is a review candidate. It can describe an exit or a
  portfolio constraint rather than a conditional entry.
- “Time Horizon: not provided” is an exact field check. Other text may mention a
  horizon, and the single analyst has a different output schema and mandate.
- Rating stability compares the Research Manager with the final Portfolio
  Manager. It excludes the earlier bull/bear debate, and does not establish that
  later discussion was unnecessary: qualifiers and sizing can still change.
- Missing tool evidence is workflow-dependent. The single analyst receives its
  evidence bundle directly, so zero missing-tool flags does not mean full coverage.

The native tag API records manually applied tags with `source: human`. That is
the application path, not our reviewer's identity: these tag names explicitly
say `candidate` or `reviewed-assistant`, and `reviews.json` identifies Codex.

Native Insights returned no clustering runs or classified weeks on November 9,
2026. The inspected UI states that it runs daily after 1,000 new turns. We did not
duplicate turns, launch a judge or claim that the checks were native clusters.

Rebuild with the repository's pinned environment:

```bash
MPLCONFIGDIR=/tmp/tradingagents-mpl python articles/build_internals.py
```

Re-extract flags from private originals when authorized:

```bash
python articles/build_internals.py --campaign lab-runs/election-v1/campaign
```

Original return records stay fixed. In particular, we have not simulated the
UNH conditional order, claimed that it would avoid the loss, or measured whether
a prompt/contract fix improves future financial performance.
