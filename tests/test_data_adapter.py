"""Caller adapters isolate both routed tools and otherwise direct Yahoo paths."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from unittest import TestCase
from unittest.mock import Mock, patch

from tradingagents.agents.tools import get_verified_market_snapshot
from tradingagents.dataflows.adapter import get_data_adapter, use_data_adapter
from tradingagents.dataflows.config import run_config
from tradingagents.dataflows.router import route_to_vendor
from tradingagents.graph.trading_graph import TradingAgentsGraph


class FixtureAdapter:
    name = "fixture"

    def __init__(self, label):
        self.label = label

    def fingerprint(self):
        return sha256(self.label.encode()).hexdigest()

    def get_data(self, method, *args, **kwargs):
        return self.label+" "+method

    def instrument_context(self, ticker, asset_type, trade_date):
        return self.label+" identity "+ticker


class DataAdapterTests(TestCase):
    def test_routed_tools_never_touch_default_vendors_or_leak_failures(self):
        adapter = FixtureAdapter("selected")
        with patch("tradingagents.dataflows.router.get_vendor", side_effect=AssertionError("unapproved vendor")):
            with use_data_adapter(adapter):
                self.assertEqual(route_to_vendor("get_stock_data", "ETH-USD"), "selected get_stock_data")
                adapter.get_data = Mock(side_effect=RuntimeError("private raw error"))
                result = route_to_vendor("get_stock_data", "ETH-USD")
                self.assertIn("DATA_UNAVAILABLE", result)
                self.assertNotIn("private raw error", result)
        self.assertIsNone(get_data_adapter())

    def test_direct_snapshot_and_identity_paths_use_the_adapter(self):
        with patch("tradingagents.agents.tools.build_verified_market_snapshot", side_effect=AssertionError("Yahoo")), \
                patch("tradingagents.graph.trading_graph.resolve_instrument_identity", side_effect=AssertionError("Yahoo")):
            with use_data_adapter(FixtureAdapter("selected")):
                text = get_verified_market_snapshot.invoke({"symbol":"ETH-USD", "curr_date":"2026-01-01"})
                self.assertIn("selected get_verified_market_snapshot", text)
                graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
                graph.config = {}
                self.assertIn("selected identity", graph.resolve_instrument_context("ETH-USD", "crypto"))

    def test_required_adapter_missing_never_uses_direct_or_routed_yahoo(self):
        with run_config({"require_data_adapter": True}), \
                patch("tradingagents.agents.tools.build_verified_market_snapshot", side_effect=AssertionError("Yahoo")), \
                patch("tradingagents.dataflows.router.get_vendor", side_effect=AssertionError("Yahoo")):
            self.assertIn("DATA_UNAVAILABLE", route_to_vendor("get_stock_data", "ETH-USD"))
            self.assertIn("DATA_UNAVAILABLE", get_verified_market_snapshot.invoke({"symbol":"ETH-USD", "curr_date":"2026-01-01"}))
            graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
            graph.config = {"require_data_adapter": True}
            with self.assertRaises(ValueError):
                graph.resolve_instrument_context("ETH-USD", "crypto")

    def test_nested_and_concurrent_bindings_do_not_leak(self):
        with use_data_adapter(FixtureAdapter("outer")):
            with use_data_adapter(FixtureAdapter("inner")):
                self.assertEqual(get_data_adapter().label, "inner")
            self.assertEqual(get_data_adapter().label, "outer")
        def run(label):
            with use_data_adapter(FixtureAdapter(label)):
                return route_to_vendor("get_stock_data", "ETH-USD")
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(run, ["one", "two"])), ["one get_stock_data", "two get_stock_data"])
        self.assertIsNone(get_data_adapter())

    def test_adapter_fingerprint_invalidates_checkpoint_and_validates_metadata(self):
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.config = {"max_debate_rounds":1,"max_risk_discuss_rounds":1}
        graph.selected_analysts = ("market",)
        with use_data_adapter(FixtureAdapter("one")):
            first = graph._run_signature("crypto")
            self.assertEqual(graph.run_settings()["data_adapter"], "fixture")
        with use_data_adapter(FixtureAdapter("two")):
            self.assertNotEqual(first, graph._run_signature("crypto"))
        invalid = FixtureAdapter("three")
        invalid.name = "invalid metadata with spaces"
        with self.assertRaises(ValueError):
            with use_data_adapter(invalid):
                self.fail("invalid adapter accepted")
