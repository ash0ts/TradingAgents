"""Balanced campaign dispatcher: isolated spawned processes, shared budget ledger."""
from __future__ import annotations

import argparse
import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from tradingagents.lab.protocol import STOCKS, cases
from tradingagents.lab.runner import TREATMENTS, run_one


def dispatch(root, output, workers=8):
    design = json.loads((Path(output) / "design.json").read_text())
    stocks = STOCKS if design["stocks"] == 6 else ["MSFT", "JPM", "XOM"]
    jobs = [(root, output, case["case_id"], treatment, trial)
            for trial in range(design["trials"]) for case in cases(stocks) for treatment in TREATMENTS]
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context, max_tasks_per_child=1) as pool:
        pending = {pool.submit(run_one, *job): job for job in jobs}
        for i, future in enumerate(as_completed(pending), 1):
            try:
                row = future.result()
                print(json.dumps({"completed": i, "total": len(jobs), "case_id": row["case_id"],
                                  "treatment": row["treatment"], "trial": row["trial"],
                                  "status": row["status"], "cost_upper_usd": row["cost_upper_usd"]}), flush=True)
            except Exception as exc:
                # An uncertain paid attempt is not blindly retried.
                print(json.dumps({"completed": i, "job": pending[future], "dispatch_error": str(exc)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    dispatch(args.root, args.output, args.workers)
