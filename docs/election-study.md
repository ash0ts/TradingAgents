# Would you give this investment committee money?

This is a retrospective replay study, with Agent Lens as the investigation
surface. Frozen inputs do not erase pretrained knowledge of historical events.
The prespecified contract is `campaigns/election-2026.json`. Initial outcomes
stop at November 5, 2026. A pending outcome is not zero return or a failure.

Collect with `python -m tradingagents.dataflows.lab_collect --root lab-data/election-v1`.
Collection runs before actors. Each case names its own immutable SHA-256 bundle;
collection time and source availability are distinct. SEC facts retain accession,
period, unit, and filing date; same-day filings use the conservative end-of-day
cutoff. ALFRED responses must confirm the requested vintage in their column name.
Yahoo prices are frozen as collected (vendor corrections remain a limitation),
with raw share units reconstructed from splits. Sources and outcomes are private.

Actors receive own-stock/SPY data through the decision cutoff. The separate
outcome file is never passed to agents. A network allowlist permits only the
model and trace services during replay. Direct sentiment, identity, verified
snapshot, and routed tools all use the frozen bundle. Missing news/social data
is explicit; this release does not pretend that a current feed is a historical
archive. +/-10-session context may include future dates in study descriptions,
but evidence served to a decision always stops at its cutoff.

Every case/treatment/trial gets a new graph, empty memory directory, and separate
checkpoint namespace. Defaults are frozen before execution. Training uses only
fully matured labels preceding the cohort's first decision, with chronological
validation. No reviewed failures become untouched tests after tuning.

Measure contracts: directional accuracy is correct signed excess directions /
non-abstaining successful matured predictions; signed excess return is predicted
direction times realized stock-minus-SPY return, averaged over that same set.
Coverage is successful actionable predictions / all requested predictions;
failures and abstentions have their own counts. Forecast errors apply only to
numeric predictions. Average trials within a market case before paired contrasts;
resample cohort blocks, not individual repeated runs. Five cohorts give weak
uncertainty estimates and no evidence of election causality.

Public examples contain derived metrics and reviewed excerpts only. Raw source
material goes to `wandb/tradingagents-election-lab-evidence`; public results and
notebooks go to `wandb/tradingagents-election-lab`. Credentials stay outside git.

A precomputed `replay_view` can restrict an experiment to one common decision
brief. Its source hash and case must match the frozen bundle; every fact carries
an availability time and observation date checked against the cutoff. All data
tools respect that view, including direct snapshot, news and sentiment paths.
They return only the prescribed facts or explicit unavailability, never hidden
raw history from the larger archive. Identity remains the archived identity.
The experiment owns the feature calculation and freezes its view digest.
