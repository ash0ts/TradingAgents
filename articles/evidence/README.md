# TradingAgents election lab: evidence release

This is the complete public tabular result export for the November 5, 2026 freeze: 960 predictions, 2,880 horizon scores, 640 portfolio scenarios, 60 source-coverage cases and six selected assistant reviews. It contains no new experiment or paid model execution.

Join predictions to scores on `case_id`, `treatment`, `trial`; add `horizon_sessions` for score uniqueness. Join portfolio scenarios on `treatment`, `trial`, `decision_date`; distinguish `bps_per_side`. Each decision-date scenario starts with $100,000. Fees apply on both sides. Returns are decimals, dollars are USD. Empty numeric CSV fields are unavailable, never zero. Pending outcomes remain pending. Portfolio means are independent-scenario averages, never a concatenated equity curve.

Agent Lens links and raw source bodies are intentionally absent from this public package. The authenticated Forge notebooks provide the result-to-conversation drilldown for authorized team members. A local private crosswalk retains the exact 360 conversation mappings. Evidence SHA-256 values identify the frozen case bundle without redistributing its source content. This public package supports result reconciliation; a full agent rerun additionally requires the private source artifact and model access.

## Reproduce and check

In the TradingAgents fork, use the pinned project environment, then run:

```sh
.venv/bin/python articles/build_assets.py
.venv/bin/python articles/build_evidence.py
.venv/bin/python scripts/reconcile_campaign.py
```

`manifest.json` gives the canonical payload digest, evidence manifest, execution revision, row counts, file hashes, figure questions and limits. `method-summaries.csv` preserves denominators. `directional-denominators.csv` partitions pending first, then scored or matured Hold. Assistant review labels are selected, not representative, and are not human labels. `paired-comparisons.csv` compares with momentum after averaging trials within case: four cohort blocks and 2,000 bootstrap resamples, seed 2026. The roster does not isolate the effect of debate because prompt objectives and evidence delivery differ. Historical model knowledge remains possible.

Public Forge notebooks:
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNjA%3D
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzE%3D
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzI%3D
