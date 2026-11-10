"""Recorded scheduling amendment; the frozen actor and scientific design are unchanged."""
from __future__ import annotations

import argparse
import json
import multiprocessing
import subprocess
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

from run_debate_ablation import OUT, PROTOCOL, PUBLIC, REPO, job, sha, validate

from tradingagents.lab.evidence import canonical

AMENDMENT = PUBLIC / "dispatch-amendment.json"


def freeze():
    validate()
    assert not AMENDMENT.exists()
    assert not list(OUT.glob("*/campaign/**/started.json")), "Amendment must precede every main execution"
    rows = [json.loads(p.read_text()) for p in OUT.glob("*/qualification/**/prediction.json")]
    assert len(rows) == 8 and all(r["status"] == "success" for r in rows)
    value = {"recorded_at": datetime.now(UTC).isoformat(), "protocol_sha256": sha(PROTOCOL),
             "change": "Increase dispatch concurrency from four to sixteen worker processes for the main run only.",
             "reason": "Qualification committee executions took roughly one to two minutes. More workers reduce elapsed time while preserving all cases, arms, repetitions and pre-dispatch cost reservations. No financial qualification result was used for this choice.",
             "workers": 16, "maximum_active_model_requests": 64,
             "unchanged": ["actor and checker source", "evidence", "hypotheses", "analysis", "case membership", "cost-only design selection", "randomized dispatch order", "no retries", "$30 combined subcap and $250 global cap"],
             "limitation": "Concurrency and provider load can affect latency; latency is descriptive at this dispatch setting.",
             "qualification_latency_s": [{"case_id": r["case_id"], "treatment": r["treatment"], "latency_s": r["latency_s"]} for r in rows],
             "source_sha256": {str(p.relative_to(REPO)): sha(p) for p in [Path(__file__).resolve(), REPO / "scripts/export_debate_ablation.py"]}}
    AMENDMENT.write_bytes(canonical(value))
    print(json.dumps({"amendment_sha256": sha(AMENDMENT), "workers": 16}))


def run():
    validate()
    amendment = json.loads(AMENDMENT.read_text())
    assert amendment["protocol_sha256"] == sha(PROTOCOL)
    assert all(sha(REPO / p) == v for p, v in amendment["source_sha256"].items())
    design = json.loads((OUT / "design.json").read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    assert revision == design["actor_code_revision"]
    launch = OUT / "launch.json"
    if not launch.exists():
        launch.write_bytes(canonical({"started_at": datetime.now(UTC).isoformat(), "actor_code_revision": revision,
                                      "protocol_sha256": sha(PROTOCOL), "amendment_sha256": sha(AMENDMENT), "workers": 16}))
    jobs = iter(json.loads((OUT / "jobs.json").read_text()))
    stopped, count = False, 0
    with ProcessPoolExecutor(max_workers=16, mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1) as pool:
        pending = {}
        def launch_one():
            args = next(jobs, None)
            if args is not None:
                pending[pool.submit(job, *args)] = args
        for _ in range(16):
            launch_one()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                args = pending.pop(future)
                try:
                    row = future.result()
                    count += 1
                    print(json.dumps({"completed": count, "case": row["case_id"], "arm": row["treatment"], "trial": row["trial"], "status": row["status"], "contract": row["execution_check"]["status"], "cost": row["cost_upper_usd"], "error": row.get("error")}), flush=True)
                    if "Budget" in row.get("error", ""):
                        stopped = True
                except Exception as exc:
                    print(json.dumps({"job": args, "dispatch_error": str(exc)}), flush=True)
                    stopped = True
                if not stopped:
                    launch_one()
    if stopped:
        raise RuntimeError("Launches stopped; preserve and inspect started attempts")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "run"))
    freeze() if parser.parse_args().command == "freeze" else run()
