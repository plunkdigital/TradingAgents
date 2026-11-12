"""Optional news evidence uses the existing analyst/tool loop and budget."""
import pytest

from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.dataflows.adapter import use_data_adapter
from tests.test_graph_end_to_end import ARGS, ScriptedModel, _graph, offline
from tests.test_required_market_tools import EarlyFinishModel, ToolRecorder


REQUIRED = ['get_global_news', 'get_macro_indicators']


class Source:
    name = 'synthetic_news'

    def __init__(self):
        self.calls = []

    def get_data(self, method, *args, **kwargs):
        self.calls.append(method)
        return 'Synthetic dated evidence; not independently verified.'

    def instrument_context(self, *args, **kwargs):
        return 'Synthetic scoped news and nominal rates; no source fallback.'

    def fingerprint(self):
        return 'a' * 64


class NewsModel(EarlyFinishModel):
    ignore_macro: bool = False

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.ignore_macro and self.selected == REQUIRED[1]:
            return ScriptedModel._generate(self, messages, stop, run_manager, **kwargs)
        return super()._generate(messages, stop, run_manager, **kwargs)


@pytest.mark.parametrize('limit,ignore_macro,expected', [
    (5, False, REQUIRED), (1, False, REQUIRED[:1]), (5, True, REQUIRED[:1]),
])
def test_required_news_calls_use_real_tools_and_existing_limits(tmp_path, monkeypatch, offline, limit, ignore_macro, expected):
    monkeypatch.setitem(ARGS, 'curr_date', '2026-11-10')
    monkeypatch.setitem(ARGS, 'indicator', '10y_treasury')
    source = Source()
    recorder = ToolRecorder()
    model = NewsModel(callbacks=[recorder], ignore_macro=ignore_macro)
    with use_data_adapter(source):
        graph = _graph(tmp_path, monkeypatch, model, selected_analysts=['news'],
                       require_data_adapter=True, news_required_tools=REQUIRED, max_tool_rounds=limit)
        graph.callbacks = [recorder]
        graph.propagate('XAU-USD-SPOT', '2026-11-10', asset_type='commodity')
    assert recorder.names == expected
    assert source.calls == expected
    assert recorder.starts == len(model.calls)
    assert model.selections[:len(expected)] == expected
    assert offline == set()


def test_default_news_analyst_keeps_model_selected_tools(tmp_path, monkeypatch, offline):
    model = EarlyFinishModel()
    graph = _graph(tmp_path, monkeypatch, model, selected_analysts=['news'])
    graph.propagate('NVDA', '2026-01-09')
    assert model.selections and set(model.selections) == {None}


@pytest.mark.parametrize('setting', ['get_global_news', None, ['unknown'],
                                     ['get_global_news', 'get_global_news'], [{}]])
def test_invalid_required_news_configuration_is_rejected(setting):
    with pytest.raises(ValueError, match='news_required_tools'):
        create_news_analyst(EarlyFinishModel(), setting)


def test_news_requirements_change_checkpoint_identity(tmp_path, monkeypatch, offline):
    baseline = _graph(tmp_path, monkeypatch, ScriptedModel(), selected_analysts=['news'])
    required = _graph(tmp_path, monkeypatch, ScriptedModel(), selected_analysts=['news'], news_required_tools=REQUIRED)
    assert baseline._run_signature('commodity') != required._run_signature('commodity')
