# Research export contract

`TradingAgentsGraph.export_research(final_state, observations=(), completed_at=None)`
returns a validated JSON-safe dictionary with `schema_version: "1.0"`. It performs
no inference, market-data requests or financial execution. Existing `propagate`,
CLI prose, reports and rating behavior remain available.

The export includes ticker, analysis date, asset type, completion timestamp,
allowlisted provider/model metadata, narrative/reports and the final typed
`PortfolioDecision`. `decision_mode` explicitly distinguishes `structured`,
`free_text` and `unavailable`. Fallback clears the typed value; a rating quoted in
narrative never replaces the typed final rating. Consumers must validate the
contract version, requested identity and provider/model metadata.

Optional `material_risks` and `source_urls` preserve the Portfolio Manager's
structured claims without an additional extraction call. Missing fields remain
empty/unknown. Price targets are model-facing research fields, not broker quotes,
quantities or execution instructions.

Callers can supply validated `ToolObservation` records: invocation ID/tool name,
aware start/end timestamps, returned/error status and SHA256/byte count of the
actual returned payload. Tool arguments, raw payloads and error strings are not
required. These records attest observed tool activity; a hash does not establish
data completeness, source licensing, publication time, citation correctness or
successful independent URL retrieval. `source_verification` is explicitly
`not_performed`. Model URL claims must not become verified sources or executable
orders merely because the decision schema validated.

The public data models and builder are in `tradingagents.research_export`.
Its focused checks can run with standard-library unittest discovery in an isolated
environment with dotenv disabled; the existing project suite uses optional pytest.
Neither test command should load real credential files or use live providers.

## Caller data adapter

`tradingagents.dataflows.adapter.use_data_adapter(adapter)` scopes an explicit
trusted Python object to one run. It supplies `name`, a SHA256 configuration/code
`fingerprint()`, `instrument_context(ticker, asset_type, trade_date)` and
`get_data(method, *args, **kwargs) -> str`. Bind it around graph construction,
propagation and export. This API loads no plugin paths, packages or remote tools.
Callers own source approval, identity validation, date bounds, request budgets,
provenance, caching, licensing and resource cleanup.

Routed data tools and the otherwise direct identity/snapshot paths use the bound
adapter. Missing methods, empty replies and errors produce unavailable data;
they never select built-in vendors. Social posts are unavailable under an adapter.
Set `require_data_adapter=True` to reject a missing binding, including in tool
contexts. The default is false and existing runs are unchanged. Context variables
propagate through LangGraph's parallel tool tasks. The adapter fingerprint affects
checkpoint identity and is exported with its name in `model_metadata`.

This hook does not assert that adapter data supports OHLC, indicators, news or
historical research. Adapters must return explicit unavailable results for those
they cannot supply. A returned string and valid decision schema do not establish
source completeness, verified citations, profitability or permission to trade.
