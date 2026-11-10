"""Machine-boundary checks runnable with unittest or the optional pytest suite."""
from datetime import datetime, timezone
from unittest import TestCase
from unittest.mock import MagicMock

from pydantic import ValidationError

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision
from tradingagents.graph.propagation import Propagator
from tradingagents.research_export import ResearchExport, build_research_export


NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def state(rating="Hold"):
    decision = PortfolioDecision(rating=rating, executive_summary="A qualified conclusion.",
        investment_thesis="Evidence from the supplied reports.", time_horizon="Six months",
        material_risks=["Evidence may become stale."], source_urls=["https://example.test/source"])
    return {"company_of_interest": "SMR.AX", "trade_date": "2026-11-09", "asset_type": "stock",
        "final_rating": rating, "portfolio_decision": decision.model_dump(mode="json"),
        "portfolio_decision_mode": "structured", "final_trade_decision": "Narrative may quote another rating.",
        "market_report": "Dated market observations."}


class ResearchExportTests(TestCase):
    def test_all_ratings_preserve_typed_claims_without_verifying_them(self):
        for rating in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            with self.subTest(rating=rating):
                result = build_research_export(state(rating), {"version": "0.7.1", "backend_url": "private-endpoint",
                    "api_key": "synthetic-key", "results_dir": "private-path"}, completed_at=NOW)
                self.assertEqual(result["rating"], rating)
                self.assertEqual(result["decision"]["material_risks"], ["Evidence may become stale."])
                self.assertEqual(result["decision"]["source_urls"], ["https://example.test/source"])
                self.assertEqual(result["source_verification"], "not_performed")
                self.assertEqual(set(result["model_metadata"]), {"version", "llm_provider", "quick_think_provider",
                    "deep_think_provider", "quick_think_llm", "deep_think_llm"})
                self.assertIsNotNone(ResearchExport.model_validate(result).decision)

    def test_fallback_and_unavailable_never_export_a_stale_typed_decision(self):
        original = state()
        fallback = {**original, "portfolio_decision": None, "portfolio_decision_mode": "free_text", "final_rating": "REVIEW"}
        self.assertIsNone(build_research_export(fallback, {}, completed_at=NOW)["decision"])
        for overrides in ({"portfolio_decision_mode": "free_text"}, {"final_rating": "Sell"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                build_research_export({**original, **overrides}, {}, completed_at=NOW)
        initial = Propagator().create_initial_state("ETH-USD", "2026-11-09", asset_type="crypto")
        export = build_research_export(initial, {}, completed_at=NOW)
        self.assertEqual(export["decision_mode"], "unavailable")
        self.assertIsNone(export["decision"])

    def test_observations_require_bounded_time_and_output_digest(self):
        observation = {"run_id": "tool-1", "tool_name": "get_news", "started_at": NOW,
            "completed_at": NOW, "status": "returned", "output_sha256": "a"*64, "output_bytes": 10}
        export = build_research_export(state(), {}, completed_at=NOW, observations=[observation])
        self.assertEqual(export["observations"][0]["output_sha256"], "a"*64)
        for changes in ({"output_sha256": None}, {"completed_at": NOW.replace(year=2027)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                build_research_export(state(), {}, completed_at=NOW, observations=[{**observation, **changes}])
        with self.assertRaises(ValidationError):
            ResearchExport.model_validate({**export, "schema_version": "2.0"})

    def test_public_graph_export_and_provider_context_protocol(self):
        from tradingagents.graph.trading_graph import TradingAgentsGraph
        graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
        graph.run_settings = lambda: {"version": "0.7.1"}
        self.assertEqual(graph.export_research(state(), completed_at=NOW)["rating"], "Hold")
        graph.propagator = Propagator()
        graph.resolve_instrument_context = lambda *args: "Verified test identity"
        portfolio = MagicMock()
        portfolio.render.return_value = "ABC 2 shares; Gold 1.25 provider-native units; cash unknown"
        initial = graph.create_run_state("ABC", "2026-11-09", portfolio=portfolio)
        self.assertIn("Gold 1.25", initial["portfolio_context"])

    def test_manager_retains_typed_decision_and_clears_it_on_fallback(self):
        manager_state = Propagator().create_initial_state("SMR.AX", "2026-11-09")
        manager_state.update(investment_plan="Qualified research", trader_investment_plan="No execution")
        llm = MagicMock()
        llm.with_structured_output.return_value.invoke.return_value = PortfolioDecision.model_validate(state()["portfolio_decision"])
        output = create_portfolio_manager(llm)(manager_state)
        self.assertEqual(output["portfolio_decision"]["rating"], "Hold")
        self.assertEqual(output["portfolio_decision_mode"], "structured")
        llm.with_structured_output.side_effect = NotImplementedError
        llm.invoke.return_value.content = "**Rating**: Sell"
        output = create_portfolio_manager(llm)({**manager_state, **output})
        self.assertEqual(output["portfolio_decision_mode"], "free_text")
        self.assertIsNone(output["portfolio_decision"])
