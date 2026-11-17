"""Two frozen development arms: a shared brief, with/without citation enforcement."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import random
import subprocess
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.lab.brief import MODES, build_brief
from tradingagents.lab.budget import Ledger, choose_design
from tradingagents.lab.evidence import EvidenceStore, canonical
from tradingagents.lab.protocol import STOCKS, cases
from tradingagents.lab.runner import TREATMENTS, run_one

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / 'lab-data/election-v1'
OUT = REPO / 'lab-runs/election-evidence-v3'
PUBLIC = REPO / 'studies/common-evidence-v3'
LEDGER = REPO / 'lab-runs/election-v1/budget.sqlite'
PROTOCOL = PUBLIC / 'protocol.json'
CAMPAIGN = 'election-evidence-v3'
CAP = 30
SEED = 20261109
QUALIFICATION_CASE = 'midterms-2022-before-UNH'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze():
    if PROTOCOL.exists():
        raise RuntimeError('Preserve the already frozen protocol')
    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    sources = [str(p.relative_to(REPO)) for p in sorted((REPO / 'tradingagents').rglob('*.py'))]
    sources += ['scripts/run_evidence_campaign.py', 'notebooks/requirements.lock', 'pyproject.toml']
    views = {case: build_brief(EvidenceStore(ROOT).get(key), key) for case, key in manifest['cases'].items()}
    for case, view in views.items():
        path = OUT / 'briefs' / (case + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(canonical(view))
    protocol = {
        'campaign_id': CAMPAIGN, 'frozen_at': datetime.now(UTC).isoformat(),
        'question': 'With identical observed facts for every role, does requiring exact final citations change executable coverage, source attribution, allocations and exploratory outcomes?',
        'decision': 'Repair unequal evidence access and expose stale observations; test a citation contract before any forward trading study.',
        'study_kind': 'Retrospective development study on previously inspected cases; no untouched test claim.',
        'arms': list(MODES), 'treatments': TREATMENTS, 'membership': cases(), 'target_trials': 2,
        'arm_difference': 'cited-evidence adds citation instructions, structured cited observations, explicit gap fields, and an execution gate. Both arms have the exact same brief, missing-source policy, execution mandate, receipt and model settings.',
        'shared_changes_from_v2': ['Same compact decision brief at every role, including SPY',
                                  'Tools restricted to the brief; raw histories excluded from both new arms',
                                  'SEC reporting dates and age explicit; no historical calendar supplied',
                                  'No event dates from model memory; forecasts labeled as judgments',
                                  'Deterministic receipt separates principal, entry fee and remaining cash'],
        'qualification': {'case_id': QUALIFICATION_CASE, 'arms': list(MODES), 'treatments': TREATMENTS},
        'design_selection': 'Use sum of both-arm qualification costs for each treatment, 2x margin, then largest affordable balanced 6 stocks/2 trials, 6/1, 3/2, 3/1. Fallback MSFT/JPM/XOM. No outcome or acceptance-rate selection.',
        'schedule': {'seed': SEED, 'rule': 'Shuffle case/treatment/trial blocks; randomize arm order within each block. No service seed is assumed.'},
        'actor_settings': {'quick': 'gpt-6-luna', 'default_deep': 'gpt-6-sol', 'other_deep': 'gpt-6-luna',
                           'max_output_tokens': 4096, 'sdk_retries': 0, 'llm_judge': None},
        'budget': {'additional_cap_usd': CAP, 'global_cap_usd': 250, 'initial_totals': Ledger(LEDGER).totals(),
                   'shared_ledger': '../../lab-runs/election-v1/budget.sqlite',
                   'infra': 'Original $175 holds preserved; no assumption that notebook infrastructure is free.'},
        'prices_verified_on': '2026-11-09',
        'price_sources': ['https://developers.openai.com/api/docs/models/gpt-6-luna', 'https://developers.openai.com/api/docs/models/gpt-6-sol'],
        'evidence_manifest_sha256': sha(ROOT / 'manifest.json'), 'outcomes_sha256': sha(ROOT / 'outcomes.json'),
        'freeze_through': manifest['freeze_through'], 'evidence_version': manifest['version'],
        'brief_sha256': {case: view['view_sha256'] for case, view in views.items()},
        'source_sha256': {p: sha(REPO / p) for p in sources},
        'metrics': {
            'primary': 'Contract/citation acceptance and explicit abstention / all requested executions, by arm and treatment; report actor failures separately.',
            'citation': 'Exact IDs, numeric values, units and dates in required slots, matching brief hash and missing-source set. This is not a complete prose-factuality metric.',
            'financial': 'Fresh $100,000 independent six-stock/date accounts; next close entry, five-session hold, 10 bps per side and 0/5/25 sensitivities. Pending 2026 outcomes stay null.',
            'selection_control': 'Counterfactual SPY with exactly each accepted sleeve allocation, same timing/cost rules and no model expense; subtract P&L to separate selection from cash exposure. This is a diagnostic, not an independent forecast.',
            'paired': 'Cited minus shared on identical case/treatment/trial. Collapse repetitions and stock sleeves to date accounts before four-cohort block bootstrap; show 8 matured dates.',
            'directional': 'Only accepted five-session Buy/Overweight/Underweight/Sell calls with matured outcomes. Hold and cash abstentions have no directional grade.',
            'historical': 'Keep original and v2 executions unchanged; comparisons to them are nonconcurrent and bundled. Original statistical/ML baselines had different information access.',
        },
        'review': {'prespecified_cases': ['midterms-2022-before-UNH','presidential-2024-after-NVDA','control-2023-after-UNH','control-2025-after-UNH','control-2023-before-AAPL'],
                   'selection': 'All treatments, arms and trials for these cases; additionally strongest, weakest and seeded-random matured accounts displayed with selection rules.',
                   'reviewer': 'Codex assistant, not a human financial-domain reviewer',
                   'scope': 'Final prose/order agreement, missing-source acknowledgment, observable event/date assertions, and reliance on stale SEC periods. Preserve quotes and precise reason; do not equate exact citation matching with semantic truth.'},
        'stop': 'Stop new launches on budget or frozen-source drift. Never retry an uncertain started attempt or silently replace an actor failure. No prompt tuning after outcomes.',
        'privacy': 'Raw snapshots, role reports and brief facts remain private. Public exports allow derived metrics, citation counts, review labels and authenticated links.',
        'limitations': ['Retrospective pretrained knowledge cannot be erased.', 'Only 8 matured dates in 4 cohorts; repetitions are not independent market observations.',
                        'Missing news/social/event calendar: limited numeric evidence, not a test of reaction to actual election news.',
                        'Feature compression differs from older campaigns and numerical baselines.',
                        'A citation can resolve exactly while failing to support a narrative inference.',
                        'Citation instructions/schema/gate are one bundled intervention; role contexts still differ through debate.'],
        'reproduce': 'python scripts/run_evidence_campaign.py qualify; python scripts/run_evidence_campaign.py select; python scripts/run_evidence_campaign.py run',
    }
    PROTOCOL.write_bytes(canonical(protocol))
    print(json.dumps({'protocol_sha256': sha(PROTOCOL), 'briefs': len(views)}))


def validate():
    protocol = json.loads(PROTOCOL.read_text())
    for name, expected in protocol['source_sha256'].items():
        if sha(REPO / name) != expected:
            raise RuntimeError('Frozen source drift: ' + name)
    assert sha(ROOT / 'manifest.json') == protocol['evidence_manifest_sha256']
    assert sha(ROOT / 'outcomes.json') == protocol['outcomes_sha256']
    return protocol


def job(mode, case, treatment, trial, phase, sleeves):
    validate()
    return run_one(ROOT, OUT / mode, case, treatment, trial, phase, campaign_id=CAMPAIGN + '/' + mode,
                   execution_contract=True, evidence_mode=mode, budget_path=LEDGER,
                   budget_prefix=CAMPAIGN + '/', campaign_cap_usd=CAP, sleeves=sleeves)


def run(jobs, workers):
    jobs = iter(jobs)
    count, stopped = 0, False
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'), max_tasks_per_child=1) as pool:
        pending = {}
        def launch():
            args = next(jobs, None)
            if args is not None:
                pending[pool.submit(job, *args)] = args
        for _ in range(workers):
            launch()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                args = pending.pop(future)
                try:
                    row = future.result()
                    count += 1
                    print(json.dumps({'completed': count, 'arm': args[0], 'case_id': row['case_id'], 'treatment': row['treatment'],
                                      'trial': row['trial'], 'status': row['status'], 'contract': row['execution_check']['status'],
                                      'cost_usd': row['cost_upper_usd'], 'error': row.get('error')}), flush=True)
                    if 'Budget' in row.get('error', ''):
                        stopped = True
                except Exception as exc:
                    print(json.dumps({'job': args, 'dispatch_error': str(exc)}), flush=True)
                    stopped = True
                if not stopped:
                    launch()
    if stopped:
        raise RuntimeError('Stopped; inspect saved attempts before continuation')


def select():
    rows = [json.loads(p.read_text()) for p in OUT.glob('*/qualification/**/prediction.json')]
    assert len(rows) == len(MODES) * len(TREATMENTS)
    if any(r['status'] != 'success' or r['unknown_calls'] for r in rows):
        raise RuntimeError('Qualification failed or has unknown model costs; preserve and inspect')
    costs = {t: sum(r['cost_upper_usd'] for r in rows if r['treatment'] == t) for t in TREATMENTS}
    # Both arms are already included in the per-treatment cost.
    design = choose_design(costs, allowance=CAP - sum(costs.values()))
    design.update(campaign_id=CAMPAIGN, arms=list(MODES), protocol_sha256=sha(PROTOCOL),
                  qualification_cost_usd=sum(costs.values()), actor_code_revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip())
    (OUT / 'design.json').write_bytes(canonical(design))
    for mode in MODES:
        (OUT / mode / 'design.json').write_bytes(canonical(design))
    stocks = STOCKS if design['stocks'] == 6 else ['MSFT','JPM','XOM']
    blocks = [(c['case_id'], t, i) for c in cases(stocks) for t in TREATMENTS for i in range(design['trials'])]
    rng = random.Random(SEED)
    rng.shuffle(blocks)
    jobs = []
    for c, t, i in blocks:
        modes = list(MODES)
        rng.shuffle(modes)
        jobs.extend((mode, c, t, i, 'campaign', len(stocks)) for mode in modes)
    (OUT / 'jobs.json').write_bytes(canonical(jobs))
    print(json.dumps(design, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['freeze','qualify','select','run'])
    parser.add_argument('--workers', type=int, default=10)
    args = parser.parse_args()
    if args.command == 'freeze':
        freeze()
    else:
        validate()
        if args.command == 'qualify':
            run([(m, QUALIFICATION_CASE, t, 0, 'qualification', 6) for m in MODES for t in TREATMENTS], min(args.workers, 6))
        elif args.command == 'select':
            select()
        else:
            run(json.loads((OUT / 'jobs.json').read_text()), args.workers)
