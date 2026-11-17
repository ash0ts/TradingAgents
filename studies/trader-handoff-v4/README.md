# Five allocation ratings through the trader handoff

The matched-evidence study exposed a legacy instruction that explicitly translates
Underweight into Sell, while its fresh-cash mandate maps those labels to 25% and
0% allocations. That is an instruction conflict in our harness integration, not
proof that the model disobeyed its instructions.

This separate engineering regression uses two already-reviewed UNH stock/date
cases, both evidence arms, and both committees: eight executions, one each.
`selection.json` records that selection before the main financial summaries were
computed. The single analyst does not use the trader handoff and is not included.
No financial-performance comparison is exported for this selected sample.

The repaired trader returns a typed proposal with all five ratings, its exact
mandate, and explicit order conditions. A next-close allocation must agree with
its rating; cash abstention must have zero weight. The final manager uses the
same fresh-cash definitions. Ordinary repository execution retains its existing
three-action trader. The public paired table links every new proposal to its
actual Agent Lens conversation and the corresponding pre-repair conversation.

An independent observability repair enables an optional private OTLP journal
with `TRADINGAGENTS_TRACE_JOURNAL`. It preserves actual ended spans with their
original identities and timestamps. Native readback, rather than a successful
flush call, establishes completeness. The original main campaign's lost Bull
Researcher spans were not journaled and cannot be reconstructed. Their response
and cost remain in that campaign's local evidence and financial denominator.

```sh
python scripts/run_handoff_regressions.py freeze
python scripts/run_handoff_regressions.py run
python scripts/export_handoff_regressions.py
python scripts/publish_handoff_regressions.py
```

The protocol pins the actor and runner sources before any of these eight paid
executions. They share the original durable $250 ledger and the evidence study's
combined $30 model subcap, including the stopped pilot. There are no automatic
model retries. Raw reports, OTLP payloads and detailed native spans stay in the
private evidence project. Public result rows contain derived checks and clearly
authenticated drilldown links.
