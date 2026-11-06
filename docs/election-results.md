# The committee has not earned a victory lap

The initial campaign completed 360 agent runs: 60 stock/date cases, three LLM
treatments, and two trials each. All 600 numerical/passive predictions also
completed. There were no execution failures. This is a retrospective,
prices/SEC/macro-only study: archived news and social evidence were unavailable.
The 2026 five-session outcomes remain pending at the November 5 freeze.

These descriptive results use only successful, non-abstaining, matured trials.
They are not portfolio returns; signed excess return is the predicted direction
times the realized stock-minus-SPY return. Different coverage means the rows
below are not a paired significance test.

| Method | Directional accuracy | Scored trials | Mean signed excess return |
|---|---:|---:|---:|
| Default Luna/Sol committee | 36.4% | 77 | −1.30% |
| All-Luna committee | 28.4% | 81 | −1.42% |
| Single Luna analyst | 29.6% | 81 | −1.24% |
| 20-session momentum | 34.1% | 44 | −1.11% |
| Five-session mean reversion | 67.4% | 46 | +0.34% |
| Ridge | 58.6% | 29 | +1.01% |
| XGBoost | 52.0% | 25 | +0.21% |
| Locally trained DLinear | 58.6% | 29 | +0.21% |
| Chronos Bolt Small | 48.6% | 35 | −0.97% |
| AR(5) | 30.8% | 13 | −1.85% |

Default committee minus momentum, after averaging repeated trials within case,
was −0.33 percentage points over 41 matched market cases. Its exploratory 95%
cohort-block interval was [−1.25, +0.74] percentage points. Only four cohorts have
matured outcomes. This does not establish an advantage from additional debate,
and it cannot establish an election effect. Neural pretraining may contain
historical knowledge; agents receive text that numerical baselines do not.
The committees also retain the repository's original recommendation prompts,
whereas the single analyst explicitly targets five-session performance versus
SPY. These comparisons therefore do not isolate the causal effect of debate:
the prompt objective and evidence-delivery method differ as well.

At 10 basis points per side, the mean independent $100,000 five-session scenario
P&L was $11.67 for the default committee, −$66.29 for all-Luna, and $16.49 for the
single analyst. SPY returned $458.44 and the equal-weight basket $688.05 on the
same eight matured decision dates. Agent means average two trials per date;
those trials are not additional independent market observations. Fees are
included, model expense is separate, and overlapping equity curves are never
concatenated. Inspect the notebook's exposure, abstention, cost-sensitivity,
pending-outcome, and full-denominator views before comparing methods.

## Investigation rather than a hallucination leaderboard

Agent Lens readback verified all 360 conversations, 15,058 spans, and 4,149 model
calls. Every span carried the matching evaluation Call IDs, all parent spans
were present, and token usage reconciled with the local ledger. Hosted Thread,
Spans, and Timeline views were also inspected directly.

The deterministic checks flagged 240 committee runs with unavailable tool
evidence, five possible missing-data acknowledgments, two possible unsupported
source claims, one repeated-tool candidate, and one current-price candidate.
These are candidates, not confirmed hallucinations. Six findings were reviewed
by the Codex assistant, explicitly labeled as non-human review. Five were false
positives caused by the checker missing contextual language. The versioned
regression export contains one confirmed evidence-coverage gap: a news tool
returns `DATA_UNAVAILABLE` and replay must not substitute live news. No LLM
judge was enabled and no reviewed case was used to tune these results.

## Reproducibility and cost

The paid runtime was frozen at `edaa0e68895b8f671c05d3ca382751148c784801`.
The complete evidence manifest is
`92623c2d0bf66b9c698f158e1374359303469a214dbcc110583e907abec4f6ef`.
The sanitized result payload is
`f565efe5b288eaf93540484801b2f79e5f5bf8b2242ed9a3223428b797c10096`.
Notebook sources embed this same payload; raw sources, trained weights, reports,
and the durable ledger are retained in the private evidence artifact.

Recorded campaign plus qualification token charges total **$7.683182** with zero
unknown model calls. Infrastructure remains reserved at **$175**, not reported as
spent. Charges plus reservations total **$182.683182 of $250**. The native span
readback contains 567,714,665 serialized JSON bytes; this is an audit size, not an
invoice ingestion measurement. Keep the infrastructure reserve until billing is
reconciled. Local model training hardware is unmetered.
