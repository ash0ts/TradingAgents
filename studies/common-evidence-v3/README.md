# Same facts, two decision contracts

This is a frozen **development** experiment on previously inspected retrospective
cases. `protocol.json` fixes the two arms, model settings, case grid, cost-only
design selection, review selection, feature hashes and actor source hashes before
paid execution. The underlying market evidence and November 5 outcome freeze are
unchanged. Qualification is separate from the main campaign.

- **Shared evidence:** every role gets the same compact numeric brief, including
  SPY. Tools can only repeat that brief or report missing data.
- **Cited evidence:** the same brief and execution rules, plus exact final fact
  references and a gate rejecting unresolved citations. This validates the cited
  slots, not every sentence or the investment thesis.

Both arms explicitly label stale filing periods and unavailable news/calendar
sources, and render a deterministic planned cash/fee receipt. The actor's actual
prose remains preserved. Earlier campaigns are not rewritten. Original numerical
baselines keep their earlier information sets; do not infer a fair model ranking
from differently informed systems.

The shared ledger retains the original infrastructure reservations. Additional
model work is capped at $30 within the original $250 ceiling; calls reserve before
dispatch. No model-call retry is automatic. An uncertain started attempt requires
readback, not a fresh attempt masquerading as a resume.

Reproduce in the repository environment with existing private snapshots and
credentials configured locally:

```sh
python scripts/run_evidence_campaign.py qualify
python scripts/run_evidence_campaign.py select
python scripts/run_evidence_campaign.py run
```

The public release will include every trial's derived decisions, financial
accounts, citation statuses, matched-exposure SPY diagnostic, source hashes and
links to authenticated Agent Lens conversations. Raw source material and full
reports remain in the private evidence project. Publication verification is
separate from execution completion.
