"""Optional quality fields retain the primary structured decision and legacy output."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from tradingagents.agents.schemas import PortfolioDecision,render_pm_decision
from tradingagents.research_export import ResearchExport,build_research_export
from tests.test_research_export import NOW,state


def test_quality_export_is_versioned_and_does_not_rewrite_normal_prose():
    original=state()
    before=render_pm_decision(PortfolioDecision.model_validate(original['portfolio_decision']))
    claim={'kind':'numeric_fact','statement':'A supplied nominal yield.',
        'fact_id':'treasury-'+'a'*64,'value':'4.98','unit':'percent','as_of':'2026-11-10'}
    enriched=deepcopy(original)
    enriched['portfolio_decision'].update(horizon_reason='A proposed research review window, not an operator policy.',evidence_claims=[claim])
    result=build_research_export(enriched,{},completed_at=NOW)
    assert result['schema_version']=='1.3'
    assert result['decision']['evidence_claims']==[claim]
    assert result['source_verification']=='not_performed'
    assert render_pm_decision(PortfolioDecision.model_validate(enriched['portfolio_decision']))==before
    with pytest.raises(ValidationError):ResearchExport.model_validate(result|{'schema_version':'1.0'})


def test_empty_quality_defaults_keep_legacy_export_fields_and_unknown_horizon():
    original=state();original['portfolio_decision']['time_horizon']=None
    result=build_research_export(original,{},completed_at=NOW)
    assert result['schema_version']=='1.0'
    assert result['decision']['time_horizon'] is None
    assert 'horizon_reason' not in result['decision']
    assert 'evidence_claims' not in result['decision']
    with pytest.raises(ValidationError):ResearchExport.model_validate(result|{'schema_version':'1.3'})


@pytest.mark.parametrize('changes',[{'horizon_reason':'x'*501},
    {'evidence_claims':[{'kind':'interpretation','statement':'Unverified'}]*13},
    {'evidence_claims':[{'kind':'verified','statement':'Not an allowed verification claim'}]}])
def test_quality_fields_are_bounded_and_do_not_accept_verification_labels(changes):
    original=state()['portfolio_decision']
    with pytest.raises(ValidationError):PortfolioDecision.model_validate(original|changes)
