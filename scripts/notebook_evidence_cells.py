"""Portable cells for the common-evidence study, built exclusively from public exports."""

from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def extensions(cell):
    path = ROOT / "studies/common-evidence-v3-repaired/results.json"
    if not path.exists():
        return "", "", ""
    data = json.loads(path.read_text())
    for name in ("reviews", "dashboard"):
        source = path.parent / (name + ".json")
        data[name] = json.loads(source.read_text()) if source.exists() else {}
    handoff = ROOT / "studies/trader-handoff-v4/results.json"
    if handoff.exists():
        data["handoff"] = json.loads(handoff.read_text())
    payload = base64.b64encode(zlib.compress(json.dumps(data).encode(), 9)).decode()
    common = cell(f"""
evidence3 = json.loads(zlib.decompress(base64.b64decode({payload!r})))
_intro3 = ("## Same facts, checkable decisions\\n"
           f"{{len(evidence3['rows'])}} new executions compare a shared numeric brief with the same brief plus required citations. "
           "All six stocks, all five cohorts, all three systems; one trial per arm, selected using qualification cost alone. "
           "Every role receives stock **and SPY** observations, dated SEC facts and frozen macro observations. Tools cannot recover hidden history. "
           "Old filing periods are explicit; news, social and event calendars remain unavailable. "
           "**These are previously inspected development cases. Exact citation matching does not certify the narrative or predict future returns.**")
mo.md(_intro3)
return evidence3,
""")
    first = (
        common
        + cell(r"""
_latest_options = {f"{r['case_id']} · {r['treatment']} · {r['arm']}": r['run_key'] for r in evidence3['rows']}
latest_picker = mo.ui.dropdown(_latest_options, value=next(iter(_latest_options)), searchable=True, full_width=True, label="Inspect a common-evidence execution")
latest_picker
return latest_picker,
""")
        + cell(r"""
latest_decision = next(r for r in evidence3['rows'] if r['run_key'] == latest_picker.value)
_receipt = latest_decision['execution_receipt']
mo.vstack([mo.md(f"**{latest_decision['rating']} · {latest_decision['contract_status']}**\n\n[Open its Agent Lens conversation (team access)]({latest_decision['conversation_url']})"),
    mo.ui.table([{'Case':latest_decision['case_id'], 'Brief digest':latest_decision['brief_sha256'],
                 'Evidence digest':latest_decision['evidence_sha256'], 'Model calls':latest_decision['model_calls'],
                 'Complete native trace':latest_decision['trace_complete'],
                 'Stale filing facts supplied':latest_decision['stale_facts_available'],
                 'Citation check':latest_decision['citation_check']['valid'] if latest_decision['citation_check'] else 'not required'}],selection=None,show_data_types=False),
    mo.md("### Computed execution receipt\nThis is the harness's planned accounting, separate from model prose and actual fills. Entry price and shares are unknown at decision time."),
    mo.ui.table([{'Cash deployed incl. fee ($)':_receipt['cash_deployed_usd'], 'Stock principal ($)':_receipt['stock_principal_usd'],
                 'Entry fee ($)':_receipt['entry_fee_usd'], 'Remaining cash ($)':_receipt['remaining_cash_usd'],
                 'Entry':_receipt['entry_date'], 'Exit':_receipt['exit_date']}],selection=None,show_data_types=False)])
return latest_decision,
""")
    )
    second = (
        common
        + cell(r"""
_pilot3 = evidence3['stopped_pilot']
_pilot_rows3 = [{'Case':r['case_id'],'System':r['treatment'],'Arm':r['arm'],
                 'Contract':r['contract_status'],'Cost ($)':r['cost_known_usd'],
                 'Agent Lens':mo.md(f"[Inspect (team access)]({r['conversation_url']})")} for r in _pilot3['rows']]
mo.vstack([mo.md("### Our checker failed qualification in the wild\nAn ambiguous instruction put a brief hash into the missing-source list. We stopped new launches, saved all 40 started executions, repaired the instruction, and reran qualification including the exact MSFT regression. These partial-schedule rows are excluded from financial comparisons; their costs still count. This was a harness-induced rejection, not evidence of a fabricated market fact."),
    mo.accordion({'Preserved stopped pilot · all 40 executions':mo.ui.table(_pilot_rows3,selection=None,show_data_types=False,page_size=8)}),
    mo.download(data=json.dumps(_pilot3,indent=2).encode(),filename='stopped-pilot.json',label='Download the stopped pilot')])
return
""")
        + cell(r"""
_gate_rows = []
for _s in evidence3['summaries']:
    _gate_rows.append({'Arm':_s['arm'],'System':_s['treatment'],'Requested':_s['requested'],
        'Accepted':_s['contract_counts'].get('accepted',0),'Explicit abstentions':_s['contract_counts'].get('abstained',0),
        'Rejected citations':_s['contract_counts'].get('invalid_citations',0),'Actor failures':_s['failed'],
        'Complete native conversations':_s['complete_native_conversations'],
        'Citation decisions checked':_s['citation_decisions_checked'],
        'Exact citation matches':_s['citation_decisions_valid'] if _s['arm']=='cited-evidence' else None})
mo.ui.table(_gate_rows,selection=None,show_data_types=False,label="Execution gates · missing citation tests are not zeros")
return
""")
        + cell(r"""
_reviewed3 = evidence3.get('reviews',{}).get('records',[])
_review_table3 = [{"Case":r['case_id'],"System":r['treatment'],"Arm":r['arm'],"Trial":r['trial']+1,
                  "Finding":r['finding'],"Review scope":r['scope'],"Reason":r['rationale'],
                  "Agent Lens":mo.md(f"[Inspect source (team access)]({r['conversation_url']})")} for r in _reviewed3]
mo.vstack([mo.md("### Inspect the explanations, too\nCodex assistant reviews of prespecified cases; not human financial-domain labels or an exhaustive factuality benchmark."),
           mo.ui.table(_review_table3,selection=None,show_data_types=False,page_size=8,label="Selected development reviews"),
           mo.download(data=json.dumps(_reviewed3,indent=2).encode(),filename="common-evidence-reviews.json",label="Download reviewed regression cases")])
return
""")
    )
    third = (
        common
        + cell(r"""
_financial3 = [{'Arm':s['arm'],'System':s['treatment'],'P&L ($)':s['mean_trading_pnl'],
    'Same-weight SPY ($)':s['mean_matched_SPY_pnl'],'Selection difference ($)':s['mean_selection_pnl'],
    'Invested fraction':s['mean_exposure'],'Matured dates':s['independent_dates'],
    'Graded directions':s['directional_correct']['n'],'Accuracy':s['directional_correct']['mean'],
    'Model cost ($)':s['total_model_cost_usd']} for s in evidence3['summaries']]
mo.ui.table(_financial3,selection=None,show_data_types=False,label="8 independent matured dates · 10 bps/side · model cost separate",
    format_mapping={'P&L ($)':'${:,.2f}','Same-weight SPY ($)':'${:,.2f}','Selection difference ($)':'${:,.2f}','Invested fraction':'{:.1%}','Accuracy':'{:.1%}'})
return
""")
        + cell(r"""
_uncertainty3 = []
for _method,_metrics in evidence3['paired_comparisons'].items():
    for _metric,_p in _metrics.items():
        _uncertainty3.append({'System':_method,'Metric':_metric,'Cited minus shared':_p['mean'],
                             'Exploratory 95% interval':str(_p['interval']),'Paired dates':_p['pairs'],'Cohort blocks':_p['blocks']})
mo.vstack([mo.md("### What changed between the two arms?\nFour cohort blocks are too few for a strong population claim. Matching invested capital does not match beta or volatility. Earlier campaigns used different information delivery and two trials; their results remain below as historical records."),
           mo.ui.table(_uncertainty3,selection=None,show_data_types=False,label="Paired cohort-block comparisons")])
return
""")
        + cell(r"""
_case_ids3 = {r['case_id'] for r in evidence3['rows'] if cohort.value=='All cohorts' or r['cohort']==cohort.value}
_history3 = [r for r in evidence3['trial_history'] if r['case_id'] in _case_ids3]
_history_table3 = []
for _r in _history3:
    for _version in ('original','contract','shared-evidence','cited-evidence'):
        _history_table3.append({'Case':_r['case_id'],'System':_r['treatment'],'Trial':_r['trial']+1,'Version':_version,
            'Scheduled':_r[_version+'_scheduled'],'Rating':_r[_version+'_rating'],
            'Contract':_r[_version+'_contract_status'],'Weight':_r[_version+'_target_weight'],
            'Signed excess return':_r[_version+'_signed_excess_return'],
            'Agent Lens':mo.md(f"[Open (team access)]({_r[_version+'_conversation_url']})") if _r[_version+'_conversation_url'] else 'not scheduled'})
mo.vstack([mo.md("### Every trial stays visible\nOriginal and contract-only campaigns ran twice; the new arms ran once. Unscheduled repeats are not failures. Filter by cohort above."),
           mo.ui.table(_history_table3,selection=None,show_data_types=False,page_size=12,label="Four versions · individual trial history"),
           mo.download(data=json.dumps(_history3,indent=2).encode(),filename="all-trial-versions.json",label="Download trial history")])
return
""")
        + cell(r"""
_accounts3 = [r for r in evidence3['portfolios'] if cohort.value=='All cohorts' or r['cohort']==cohort.value]
mo.vstack([mo.md("### Accounts, costs and pending horizons\nThe download includes every fee sensitivity (0/5/10/25 bps), both arms, and the same-weight SPY control. Current 2026 five-session outcomes stay pending at the November 5 freeze."),
    mo.ui.table([{k:r[k] for k in ('arm','treatment','decision_date','trial','bps_per_side','status','trading_pnl','matched_SPY_pnl','selection_pnl')} for r in _accounts3],selection=None,show_data_types=False,page_size=10),
    mo.download(data=json.dumps(_accounts3,indent=2).encode(),filename="common-evidence-accounts.json",label="Download all selected accounts")])
return
""")
        + cell(r"""
_examples3 = []
for _e in evidence3['examples']:
    _sources = [r for r in evidence3['rows'] if (r['arm'],r['treatment'],r['decision_date'],r['trial'])==(_e['arm'],_e['treatment'],_e['decision_date'],_e['trial'])]
    _examples3.append({'Selection':_e['selection'],'Arm':_e['arm'],'System':_e['treatment'],
                      'Decision date':_e['decision_date'],'P&L ($)':_e['trading_pnl'],
                      'Selection difference ($)':_e['selection_pnl'],
                      'Source conversations':mo.md(' · '.join(f"[{r['ticker']}]({r['conversation_url']})" for r in _sources))})
mo.vstack([mo.md("### Inspect a winner, a loser and a random account\nSelected separately for each arm and system by account P&L, with seed 20261109 for the random account. These examples describe the observed development sample; they do not determine the prespecified explanation-review set. Conversation links require team access."),
           mo.ui.table(_examples3,selection=None,show_data_types=False,page_size=9)])
return
""")
    )
    trace_health = cell(r"""
_trace3 = evidence3['hosted']
_gap3 = _trace3['incomplete_conversations'][0]
_trace_text3 = (f"**Native trace readback:** {_trace3['complete_conversations']}/{_trace3['conversations']} conversations reconcile all recorded model, tool and subagent activity. "
    "One Bull Researcher subagent and its model span were lost after an export timeout. Its response and charge remain in the local record and financial results; its exact request cannot be recovered. "
    f"[Inspect the incomplete conversation (team access)](https://forge.coreweave.com/agent-lens/wandb/tradingagents-election-lab-evidence/conversations/{_gap3['conversation_id']}). "
    "No span was reconstructed and no model was rerun to replace it.")
mo.md(_trace_text3)
return
""")
    handoff_cells = cell(r"""
_handoff3 = evidence3.get('handoff',{})
_handoff_rows3 = [{'Case':r['case_id'],'Arm':r['arm'],'System':r['treatment'],
                   'Previous trader action':r['previous_trader_action'],'Repaired trader action':r['trader_action'],
                   'Proposed weight':r['proposed_weight'],'Final weight':r['final_target_weight'],
                   'Final gate':r['final_contract_status'],
                   'Original conversation':mo.md(f"[Before (team access)]({r['previous_conversation_url']})"),
                   'Repaired conversation':mo.md(f"[After (team access)]({r['conversation_url']})")} for r in _handoff3.get('rows',[])]
mo.vstack([mo.md("### Repair the instruction before blaming the trader\nThe old trader explicitly translated Underweight into Sell, although the fresh-cash mandate maps those to 25% and 0%. A separate eight-case engineering regression gives trader and manager one five-rating vocabulary. These selected runs do not supply another financial comparison. Actual ended spans are now journaled privately before process exit; that cannot recover the earlier unjournaled loss."),
           mo.ui.table(_handoff_rows3,selection=None,show_data_types=False,page_size=8,label="Separate handoff regressions · exact original and repaired executions"),
           mo.download(data=json.dumps(_handoff3,indent=2).encode(),filename="handoff-engineering-regressions.json",label="Download handoff checks")])
return
""")
    budget = cell(r"""
_b3 = evidence3.get('handoff',{}).get('budget',evidence3['budget'])
_budget3 = (f"**Latest shared ledger:** ${_b3['cost_known_usd']:.6f} known model charges plus "
            f"${_b3['infrastructure_reserved_usd']:.2f} infrastructure reservations = ${_b3['cost_upper_usd']:.6f} known or reserved against $250. "
            "Infrastructure awaits invoice reconciliation; local training hardware is unmetered. Earlier budget tables are dated release snapshots.")
mo.md(_budget3)
return
""")
    return first + trace_health + budget, second + handoff_cells + trace_health + budget, third + trace_health + budget
