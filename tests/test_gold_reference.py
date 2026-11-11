"""Native gold data uses synthetic credentials/HTTP and stores no source payloads."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from tradingagents.dataflows.vendors.gold_api import GoldReferenceAdapter, GoldDataUnavailable, GoldHistoryNotConfigured
from tradingagents.research_export import build_research_export

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)


def history():
    return [{"day":(NOW-timedelta(days=day)).date().isoformat(),"avg_price":str(4000+day)} for day in range(90,0,-1)]


def adapter(history_changes=lambda data:data, quote_changes=None):
    calls=[]
    def get(url, **kwargs):
        calls.append((url,kwargs))
        data = history_changes(history()) if url.endswith('/history') else {
            "symbol":"XAU","currency":"USD","name":"Gold","price":"4100.25","updatedAt":NOW.isoformat(),**(quote_changes or {})}
        response=Mock(status_code=200,headers={"content-type":"application/json"},url=url)
        response.iter_content.return_value=[json.dumps(data).encode()]
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        return response
    client=Mock(get=Mock(side_effect=get))
    result=GoldReferenceAdapter(enabled=True,licensed=True,api_key="synthetic-history-key",client=client,clock=lambda:NOW,sleep=lambda seconds:None)
    return result,calls


def test_missing_history_key_makes_no_http_or_model_call(monkeypatch):
    monkeypatch.delenv('GOLD_API_KEY',raising=False)
    client=Mock()
    source=GoldReferenceAdapter(enabled=True,licensed=True,client=client)
    with pytest.raises(GoldHistoryNotConfigured):
        source.prepare()
    assert source.requests==0
    client.get.assert_not_called()


def test_daily_averages_and_spot_are_cached_only_in_memory():
    source,calls=adapter()
    source.prepare()
    source.prepare()
    assert len(calls)==2
    assert calls[0][1]['params']['aggregation']=='avg'
    assert calls[0][1]['headers']['x-api-key']=='synthetic-history-key'
    assert 'x-api-key' not in calls[1][1]['headers']
    assert all(call[1]['allow_redirects'] is False for call in calls)
    source.instrument_context('XAU-USD-SPOT','commodity','2026-11-10')
    text=source.get_data('get_stock_data','XAU-USD-SPOT','2026-10-01','2026-11-10')
    assert 'daily average' in text and 'not OHLC' in text
    source.get_data('get_verified_market_snapshot','XAU-USD-SPOT','2026-11-10',30)
    coverage=source.coverage()
    assert coverage['history_count']==90
    assert set(coverage['required_tools'].values())=={'available'}
    assert 'synthetic-history-key' not in json.dumps(coverage)
    assert 'synthetic-history-key' not in json.dumps(source.receipts)
    assert len(calls)==2
    source.close()
    assert source.api_key=='' and source.history==[] and source.quote is None


@pytest.mark.parametrize('change',[
    lambda rows:rows[::-1],lambda rows:rows[:-10],lambda rows:rows[:5],
    lambda rows:rows+[rows[-1]],lambda rows:rows[:30]+rows[40:],
    lambda rows:[*rows[:-1],dict(rows[-1],avg_price='NaN')],
    lambda rows:[*rows[:-1],dict(rows[-1],day='2026-11-11')],
])
def test_invalid_history_fails_without_using_a_different_source(change):
    source,calls=adapter(history_changes=change)
    with pytest.raises(GoldDataUnavailable):
        source.prepare()
    assert source.stopped and len(calls)==1


def test_wrong_spot_identity_and_stale_prepared_data_are_rejected():
    source,calls=adapter(quote_changes={'currency':'EUR'})
    with pytest.raises(GoldDataUnavailable):
        source.prepare()
    source,calls=adapter()
    source.prepare()
    source.clock=lambda:NOW+timedelta(minutes=16)
    assert source.get_data('get_verified_market_snapshot','XAU-USD-SPOT','2026-11-10').startswith('DATA_UNAVAILABLE')
    assert source.coverage()['required_tools']['get_verified_market_snapshot']=='unavailable'
    assert len(calls)==2


def test_coverage_is_a_separate_versioned_contract_without_market_values():
    source,_=adapter()
    source.prepare()
    source.get_data('get_stock_data','XAU-USD-SPOT','2026-10-01','2026-11-10')
    source.get_data('get_verified_market_snapshot','XAU-USD-SPOT','2026-11-10')
    state={'company_of_interest':'XAU-USD-SPOT','trade_date':'2026-11-10','asset_type':'commodity',
        'portfolio_decision_mode':'unavailable','final_rating':None,'market_report':'Source observations, optional indicators unavailable.'}
    exported=build_research_export(state,{},coverage=source.coverage(),completed_at=NOW)
    assert exported['schema_version']=='1.2'
    assert 'current_spot' not in json.dumps(exported['coverage'])
    assert exported['coverage']['history_measure']=='daily_average'
    assert build_research_export(state,{},completed_at=NOW)['schema_version']=='1.1'


@pytest.mark.parametrize('status',[302,429,503])
def test_http_failures_do_not_retry_or_expose_the_key(status):
    source,calls=adapter()
    response=Mock(status_code=status,headers={"content-type":"application/json"})
    response.__enter__=Mock(return_value=response)
    response.__exit__=Mock(return_value=False)
    source.http.get.side_effect=None
    source.http.get.return_value=response
    with pytest.raises(GoldDataUnavailable) as error:
        source.prepare()
    assert 'synthetic-history-key' not in str(error.value)
    assert source.requests==1 and source.stopped
    source.http.get.assert_called_once()
