"""The single supported Weave compatibility boundary; native tracing owns LLMs."""
from __future__ import annotations

from contextlib import contextmanager


class EvaluationBridge:
    def __init__(self, project, campaign, treatment, dataset):
        import weave
        self.client = weave.init(project, settings={"implicitly_patch_integrations": False})
        self.logger = weave.EvaluationLogger(name=f"{campaign}/{treatment}", model={"name": treatment},
                                             dataset=dataset, eval_attributes={"campaign_id": campaign}, trace_scores=False)

    @contextmanager
    def prediction(self, case, trial, evidence):
        with self.logger.log_prediction(inputs={"case": case, "evidence_sha256": evidence},
                                         example_id=case["case_id"], trial_index=trial) as prediction:
            attrs = {"weave.eval.run_id": prediction.evaluate_call.id,
                     "weave.eval.predict_and_score_call_id": prediction.predict_and_score_call.id,
                     "weave.eval.example_id": case["case_id"], "weave.eval.trial_index": trial}
            yield prediction, attrs

    def finish(self, summary):
        self.logger.log_summary(summary)
        self.client.flush()
