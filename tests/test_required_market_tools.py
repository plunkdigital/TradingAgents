"""Opt-in evidence calls stay inside the ordinary analyst/tool loop."""
import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.turn import _missing_required_tool
from tradingagents.dataflows.adapter import use_data_adapter
from tests.test_gold_reference import adapter
from tests.test_graph_end_to_end import ARGS, ScriptedModel, _graph, offline

REQUIRED = ['get_stock_data', 'get_verified_market_snapshot']


class EarlyFinishModel(ScriptedModel):
    """Would finish after the first tool result unless a tool is selected."""
    selected: str | None = None
    selections: list = Field(default_factory=list)
    ignore_snapshot: bool = False

    def bind_tools(self, tools, **kwargs):
        selected = kwargs.get('tool_choice')
        self.selections.append(selected)
        return self.model_copy(update={'tools': tuple(tools), 'selected': selected})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not self.selected or self.ignore_snapshot and self.selected == REQUIRED[1]:
            return super()._generate(messages, stop, run_manager, **kwargs)
        self._count()
        tool = self.tools[0]
        call = {'name': tool.name, 'id': f'call_{len(self.calls)}',
                'args': {k: v for k, v in ARGS.items()
                         if k in tool.tool_call_schema.model_json_schema()['properties']}}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='', tool_calls=[call]))])


class ToolRecorder(BaseCallbackHandler):
    def __init__(self):
        self.names = []
        self.starts = 0

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.names.append(serialized['name'])

    def on_chat_model_start(self, *args, **kwargs):
        self.starts += 1


@pytest.mark.parametrize('limit,ignore_snapshot,expected', [
    (5, False, REQUIRED), (1, False, REQUIRED[:1]), (5, True, REQUIRED[:1]),
])
def test_native_graph_observes_real_required_calls_with_existing_limits(
        tmp_path, monkeypatch, offline, limit, ignore_snapshot, expected):
    source, requests = adapter()
    source.prepare()
    monkeypatch.setitem(ARGS, 'curr_date', '2026-11-10')
    monkeypatch.setitem(ARGS, 'end_date', '2026-11-10')
    monkeypatch.setitem(ARGS, 'start_date', '2026-10-01')
    recorder = ToolRecorder()
    model = EarlyFinishModel(callbacks=[recorder], ignore_snapshot=ignore_snapshot)
    with use_data_adapter(source):
        graph = _graph(tmp_path, monkeypatch, model, selected_analysts=['market'],
                       require_data_adapter=True, market_required_tools=REQUIRED,
                       max_tool_rounds=limit)
        graph.callbacks = [recorder]
        state, _ = graph.propagate('XAU-USD-SPOT', '2026-11-10', asset_type='commodity')
        export = graph.export_research(state)
    assert recorder.names == expected
    assert recorder.starts == len(model.calls)
    assert export['coverage']['required_tools'] == {name: 'available' for name in expected}
    assert len(requests) == 2  # tools consume the prepared source, no extra HTTP
    assert offline == set()
    assert model.selections[:len(expected)] == expected
    source.close()


def test_default_market_analyst_keeps_model_selected_tools(tmp_path, monkeypatch, offline):
    model = EarlyFinishModel()
    graph = _graph(tmp_path, monkeypatch, model, selected_analysts=['market'])
    graph.propagate('NVDA', '2026-01-09')
    assert model.selections and set(model.selections) == {None}


@pytest.mark.parametrize('setting', ['get_stock_data', None, ['unknown'],
                                     ['get_stock_data', 'get_stock_data'], [{}]])
def test_invalid_required_tool_configuration_is_rejected(setting):
    with pytest.raises(ValueError, match='market_required_tools'):
        create_market_analyst(EarlyFinishModel(), setting)


def test_only_matching_completed_non_error_calls_satisfy_requirements():
    call = AIMessage(content='', tool_calls=[{'name': REQUIRED[0], 'args': {}, 'id': 'history'}])
    assert _missing_required_tool(REQUIRED, [call]) == REQUIRED[0]
    assert _missing_required_tool(REQUIRED, [call, ToolMessage('error', tool_call_id='history', status='error')]) == REQUIRED[0]
    assert _missing_required_tool(REQUIRED, [ToolMessage('unsolicited', tool_call_id='other', name=REQUIRED[0])]) == REQUIRED[0]
    assert _missing_required_tool(REQUIRED, [call, ToolMessage('data', tool_call_id='history')]) == REQUIRED[1]


def test_required_tools_change_checkpoint_identity(tmp_path, monkeypatch, offline):
    baseline = _graph(tmp_path, monkeypatch, ScriptedModel(), selected_analysts=['market'])
    required = _graph(tmp_path, monkeypatch, ScriptedModel(), selected_analysts=['market'],
                      market_required_tools=REQUIRED)
    assert baseline._run_signature('commodity') != required._run_signature('commodity')
