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

Commodity references use export `schema_version: "1.1"` and
`asset_type: "commodity"`; stock/crypto exports retain v1.0. Older consumers
must reject the new version rather than relabel a commodity as a stock.
Commodity identity requires a caller adapter. The caller selects market/news
analysts, supplies explicit reference units and keeps broker positions separate.
Commodity debate prompts use supply/demand and macro evidence; missing data is
not replaced by company-earnings assumptions. This adds no metals vendor, broker
integration, CLI mode, live inference or research-quality guarantee.

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

## Optional native gold reference adapter

Callers requiring market tool coverage can opt into
`config["market_required_tools"] = ["get_stock_data", "get_verified_market_snapshot"]`.
News callers may likewise opt into
`config["news_required_tools"] = ["get_global_news", "get_macro_indicators"]`.
Both defaults are empty. The existing analyst tool loop selects the next missing
tool by name and lets the model provide its arguments. These settings add no tool
rounds, source requests or fallback vendors. A provider can ignore named selection,
and a tool can return unavailable data; consumers must still validate actual
returned evidence. Configuration changes participate in checkpoint identity.
The default is empty and ordinary tool selection is unchanged. The market analyst
selects each missing tool by name, lets the model supply its arguments, and runs
the call through the existing ToolNode and callbacks. Only a corresponding
non-error ToolMessage counts as completed. This adds no source fetch outside the
tool loop, no fabricated observation and no extra tool rounds or inference budget.
Tool-disabled wrap-up still applies when rounds are spent. Providers must support
named tool selection; refusal or ignored selection must remain unavailable or
insufficient evidence at the consumer. Completed calls alone do not validate their
contents. This setting participates in the existing checkpoint signature, so
changing it cannot resume a report under the old evidence policy.

`tradingagents.dataflows.vendors.gold_api.GoldReferenceAdapter` implements the
existing public `DataAdapter` protocol. Bind it with `use_data_adapter`, prepare
it before the graph, and close it in `finally`. Existing stock/crypto sources,
provider selection, sign-in, CLI and graph defaults are unchanged.

The adapter accepts explicit XAU/XAG USD spot-reference identities, opt-in source
policy booleans, a 31-365 day history window and a bounded request budget (at least
two). It reads `GOLD_API_KEY` from the normal TradingAgents environment unless a
caller supplies a synthetic key for tests. Never copy broker credentials into it.
`history_configured()` reports presence only, without returning a credential,
creating a client, validating authentication or making a request.

Current [Gold API documentation](https://gold-api.com/llms.txt) describes free
history with a key, daily `avg` aggregation and a separate current spot endpoint.
The [free tier](https://gold-api.com/pricing) has ten history/OHLC requests per hour.
A free account/key is required for history; no paid plan is selected automatically.
The client uses one bounded history request and one spot request, with spacing,
no redirects/retries/fallback and a conservative one-hour retry boundary exposed
to callers. Only complete UTC days are included. Daily averages are not closes,
OHLC bars, volume or technical indicators. News/macro coverage is unavailable in
this adapter and must be disclosed. Public docs/schema checks are not live source
acceptance or a guarantee of provider data accuracy.

History `day` labels accept date-only strings and ISO midnight timestamps with
`T` or space separators, optional zero fractional seconds, and either no timezone
suffix or explicit `Z`/`+00:00`. Naive midnight labels are normalized to UTC only
because this endpoint documents UTC grouping. Invalid dates, intraday values,
nonzero offsets and numeric epochs remain rejected. Ordering, unique dates,
window bounds, minimum coverage and freshness checks remain enforced.

Spot freshness permits at most five seconds of future clock skew and at most
15 minutes of age, at preparation and subsequent tool use. The typed coverage
export also caps future skew at five seconds. This handles small
observed differences between the provider and caller clocks; larger future
timestamps and stale data fail closed. The original `source_updated_at` and
coverage `spot_as_of` remain unchanged, including when slightly ahead of capture.
`clock_skew_tolerance_seconds` exposes the fixed bound to diagnostic callers; it
does not configure a larger allowance. Integrations must preserve this revision's
semantics and report timing uncertainty rather than retime the source payload.

Prepared data and credentials stay in memory. The adapter does not create a
market database or save raw responses. Normal graph reporting/checkpoint behaviour
is unchanged; callers requiring temporary artifacts supply private temporary
output/cache/memory paths and clean those up after collecting their concise result.
Existing logs are not deleted automatically.

An adapter exposing `coverage()` opts into export **1.2**, with typed gold
identity, USD/troy-ounce unit, source/capture dates, daily-average history count
and window, required-tool outcomes and missing optional categories. No raw market
values appear in coverage. Adapters without coverage retain export 1.0 for
stock/crypto and 1.1 for commodities, without an extra field. Coverage and tool
hashes do not independently verify model citations or a recommendation.

Graph callbacks now reach tool execution as well as model clients. A shared
callback is not counted twice by LangChain. Validation errors remain visible as
tool failures. Commodity market instructions explicitly request `curr_date` and
respect source capabilities; existing stock/crypto instructions are preserved.
