# Repeated debate ablations

`run_one(..., treatment="luna-no-research", debate_ablation="no-research",
execution_contract=True, evidence_mode="shared-evidence")` skips only the bull/bear
research debate. The Research Manager receives the original four analyst reports
with an explicit omission notice. The Trader, risk debate and final manager remain.
`luna-no-risk` / `no-risk` skips the three risk participants and keeps the research
debate. The final manager still receives the research and trader plans. Each affected
manager is explicitly told that the omitted debate did not happen.

Both variants use Luna at every role, the same repaired five-rating handoff, fresh
cash mandate and evidence brief. The ordinary graph retains its original topology.
The treatment identity, configuration/checkpoint signature and native metadata
include the ablation. A cached prediction cannot be reused across graph variants.

This measures the total effect of removing a stage, including its computation and
context. It does not isolate social reasoning at equal compute. Repeated executions
measure stochastic variability, not independent market observations. The analysis
averages trials within each date before pairing and grouping by historical cohort.
Three prespecified comparisons use the full all-Luna committee as their control.
Four-block bootstrap intervals and sign-flip tests are exploratory; Holm adjustment
does not repair the small sample or historical pretrained knowledge.
