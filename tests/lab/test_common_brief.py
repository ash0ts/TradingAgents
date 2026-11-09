from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.dataflows.config import run_config
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.lab.brief import (
    CitedDecision,
    assess_citations,
    brief_prompt,
    build_brief,
    total_return,
)
from tradingagents.lab.evidence import cutoff, digest
from tradingagents.lab.execution import execution_check, execution_receipt, make_mandate


@pytest.fixture
def bundle():
    from datetime import date, timedelta
    days = [(date(2022, 8, 1) + timedelta(days=i)).isoformat() for i in range(99)]
    return {'case': {'case_id': 'fixture', 'ticker': 'UNH', 'decision_date': days[-1]},
            'records': [{'kind': 'sec', 'available_at': cutoff(days[-1]).isoformat(), 'content': [
                {'tag': 'Assets', 'unit': 'USD', 'val': 50, 'end': '2015-06-30', 'filed': '2015-07-29', 'form': '10-Q', 'accn': 'old'}]}],
            'prices': {s: [{'date': d, 'close': 100+i, 'split': 1, 'dividend': 0} for i, d in enumerate(days)] for s in ('UNH', 'SPY')}}


@pytest.fixture
def row(bundle):
    view = build_brief(bundle, digest(bundle))
    mandate = make_mandate('UNH', '2022-11-07', sessions=[
        '2022-11-07', '2022-11-08', '2022-11-09', '2022-11-10',
        '2022-11-11', '2022-11-14', '2022-11-15']).model_dump()
    citations = [{'fact_id': f['id'], **{k: f[k] for k in ('value', 'unit', 'as_of')}}
                 for f in view['facts'] if f['id'] in ('UNH.return20', 'SPY.return20')]
    decision = {'rating': 'Underweight', 'executive_summary': 'Allocate 25%.', 'investment_thesis': 'Fixture.',
                'price_target': None, 'time_horizon': '5 trading sessions', 'mandate': mandate,
                'order': {'kind': 'next_close', 'target_weight': .25, 'conditions': [], 'reason': 'Fixture.'},
                'view_sha256': view['view_sha256'], 'citations': citations, 'evidence_gaps': view['missing_sources']}
    return {'status': 'success', 'rating': 'Underweight', 'execution_mandate': mandate,
            'evidence_mode': 'cited-evidence', 'evidence_view': view, 'execution_decision': decision}


def test_brief_split_dividend_returns_and_old_filing_age(bundle):
    assert total_return([{'close': 100}, {'close': 51, 'split': 2, 'dividend': 1}], 1) == pytest.approx(.04)
    view = build_brief(bundle, digest(bundle))
    facts = {f['id']: f for f in view['facts']}
    assert facts['UNH.excess20']['value'] == 0
    assert facts['SEC.Assets.USD']['stale_over_180_days']
    assert facts['SEC.Assets.USD']['as_of'] == '2015-06-30'
    assert facts['SEC.Assets.USD']['age_days'] > 2000
    assert view['view_sha256'] == digest({k: v for k, v in view.items() if k != 'view_sha256'})
    assert 'event_calendar' in view['missing_sources']


def test_future_prices_facts_and_wrong_snapshot_are_rejected(bundle):
    with pytest.raises(ValueError, match='hash'):
        build_brief(bundle, 'wrong')
    future = deepcopy(bundle)
    future['prices']['SPY'][-1]['date'] = '2023-01-01'
    with pytest.raises(ValueError, match='future'):
        build_brief(future, digest(future))
    future = deepcopy(bundle)
    future['records'][0]['content'][0]['filed'] = '2023-01-01'
    with pytest.raises(ValueError, match='Future SEC'):
        build_brief(future, digest(future))


@pytest.mark.parametrize(('field', 'bad'), [('fact_id', 'CPI.release_date'), ('value', .99), ('unit', 'percent'), ('as_of', '2026-11-09')])
def test_bad_citation_cannot_authorize_a_trade(row, field, bad):
    assert execution_check(row)['eligible']
    row['execution_decision']['citations'][0][field] = bad
    assert not assess_citations(row['execution_decision'], row['evidence_view'])['valid']
    check = execution_check(row)
    assert check['status'] == 'invalid_citations' and check['target_weight'] == 0
    assert execution_receipt(row)['cash_deployed_usd'] == 0


def test_benchmark_and_gap_citations_required_but_no_fake_abstention(row):
    row['execution_decision']['citations'] = row['execution_decision']['citations'][:1]
    assert 'missing_price_citation:SPY' in execution_check(row)['reasons']
    row['execution_decision']['order'].update(kind='abstain', target_weight=0)
    assert execution_check(row)['status'] == 'abstained'
    row['execution_decision']['evidence_gaps'] = []
    assert execution_check(row)['status'] == 'invalid_citations'


def test_receipt_resolves_the_reviewed_fee_error(row):
    receipt = execution_receipt(row)
    assert receipt['cash_deployed_usd'] == pytest.approx(4166.6666667)
    assert receipt['stock_principal_usd'] == pytest.approx(4162.5041625)
    assert receipt['entry_fee_usd'] == pytest.approx(4.1625042)
    assert receipt['stock_principal_usd'] + receipt['entry_fee_usd'] + receipt['remaining_cash_usd'] == pytest.approx(100000 / 6)


def test_every_role_context_and_final_schema_receive_the_same_brief(row):
    config = {'evaluation_mandate': row['execution_mandate'], 'evidence_mode': row['evidence_mode'], 'replay_view': row['evidence_view']}
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = config
    with patch('tradingagents.graph.trading_graph.resolve_instrument_identity', return_value={}):
        context = graph.resolve_instrument_context('UNH', trade_date='2022-11-07')
    assert brief_prompt(row['evidence_view'], row['evidence_mode']) in context
    state = Propagator().create_initial_state('UNH', '2022-11-07', instrument_context=context)
    state.update(investment_plan='Fixture', trader_investment_plan='Fixture')
    model = Mock()
    model.with_structured_output.return_value.invoke.return_value = CitedDecision.model_validate(row['execution_decision'])
    with run_config(config):
        output = create_portfolio_manager(model)(state)
    assert output['execution_decision']['citations'] == row['execution_decision']['citations']
    assert 'Computed execution receipt (harness; not model reasoning or an actual fill)' in output['final_trade_decision']
    assert context in model.with_structured_output.return_value.invoke.call_args.args[0]
