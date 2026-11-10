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
