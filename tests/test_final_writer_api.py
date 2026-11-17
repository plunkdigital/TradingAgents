"""Caller-owned final writers replace one graph node, never verification authority."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.research_export import ResearchExport, build_research_export


NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def coverage(ticker='XAU-USD-SPOT'):
    return dict(schema_version='1.0', ticker=ticker, provider='gold_api', currency='USD', unit='troy_ounce',
        captured_at=NOW, spot_as_of=NOW, history_start=(NOW-timedelta(days=90)).date(),
        history_end=(NOW-timedelta(days=1)).date(), history_count=90, history_measure='daily_average',
        required_tools={'get_stock_data':'available', 'get_verified_market_snapshot':'available'},
        optional_unavailable=['news', 'macro', 'ohlc_indicators'])


class FinalWriterAPITests(TestCase):
    def graph(self, folder, factory=None, signature=None):
        config=deepcopy(DEFAULT_CONFIG)
        config.update(results_dir=folder+'/results', data_cache_dir=folder+'/cache',
            memory_log_path=folder+'/memory.md')
        with patch('tradingagents.graph.trading_graph.create_tier_client') as clients:
            return TradingAgentsGraph(config=config, selected_analysts=['market'],
                final_writer_factory=factory, final_writer_signature=signature)

    def test_public_constructor_replaces_final_node_and_binds_signature_to_checkpoint(self):
        node=Mock(return_value={'atomic_proposal':{'input_hash':'a'*64}})
        factory=Mock(return_value=node)
        with TemporaryDirectory() as folder, patch(
                'tradingagents.graph.setup.create_portfolio_manager', side_effect=AssertionError('Legacy writer must not be created')):
            graph=self.graph(folder, factory, 'a'*64)
            factory.assert_called_once_with(graph.deep_thinking_llm)
            result=graph.workflow.nodes['Portfolio Manager'].runnable.invoke({})
            self.assertEqual(result['atomic_proposal']['input_hash'], 'a'*64)
            first=graph._run_signature('commodity')
            graph.final_writer_signature='b'*64
            self.assertNotEqual(first, graph._run_signature('commodity'))
            graph.final_writer_signature=None
            self.assertNotIn('final_writer=', graph._run_signature('commodity'))

    def test_invalid_factory_signature_pairs_fail_before_client_creation(self):
        for factory, signature in ((lambda model:None, None), (None, 'a'*64), ('not-callable', 'a'*64),
                (lambda model:None, 'not-a-hash')):
            with patch('tradingagents.graph.trading_graph.create_tier_client') as client:
                with self.assertRaises(ValueError):
                    TradingAgentsGraph(final_writer_factory=factory, final_writer_signature=signature)
                client.assert_not_called()

    def test_atomic_output_is_versioned_and_never_a_legacy_rating_or_decision(self):
        for ticker in ('XAU-USD-SPOT', 'XAG-USD-SPOT'):
            state=Propagator().create_initial_state(ticker, '2026-11-16', asset_type='commodity')
            state.update(atomic_proposal={'schema_version':'1.0', 'input_hash':'a'*64,
                'disposition':'insufficient_evidence'}, portfolio_decision_mode='atomic_proposal',
                final_rating='REVIEW', final_trade_decision='Unverified proposal, not accepted advice.')
            result=build_research_export(state, {}, completed_at=NOW, coverage=coverage(ticker))
            self.assertEqual(result['schema_version'], '1.4')
            self.assertEqual(result['rating'], 'REVIEW')
            self.assertIsNone(result['decision'])
            for mutation in ({'schema_version':'1.3'}, {'rating':'Hold'}, {'atomic_proposal':None},
                    {'decision_mode':'structured'}, {'coverage':None}):
                with self.assertRaises(ValueError): ResearchExport.model_validate(result|mutation)
            bad=deepcopy(result); bad['atomic_proposal']['production_ready']=True
            with self.assertRaises(ValueError): ResearchExport.model_validate(bad)

    def test_atomic_proposals_are_logged_but_not_added_to_decision_memory(self):
        graph=TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph._log_state=Mock(); graph.memory_log=Mock()
        graph.record_decision('XAU-USD-SPOT', '2026-11-16', {
            'atomic_proposal':{'input_hash':'a'*64}, 'portfolio_decision_mode':'atomic_proposal',
            'final_rating':'REVIEW', 'final_trade_decision':'Unverified call.'})
        graph._log_state.assert_called_once()
        graph.memory_log.store_decision.assert_not_called()

    def test_legacy_exports_keep_their_original_shape(self):
        state=Propagator().create_initial_state('ABC', '2026-11-16')
        result=build_research_export(state, {}, completed_at=NOW)
        self.assertEqual(result['schema_version'], '1.0')
        self.assertNotIn('atomic_proposal', result)
