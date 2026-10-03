# NFL Historical-Market Odds API Transport 0.1.3 — Freeze Record

Freeze date: `2026-10-03`

Transport identity: `nfl_historical_market_odds_api_transport_0.1.3`

Status: `FROZEN ODDS API HTTPS TRANSPORT`

Executor integration: `NOT YET IMPLEMENTED`

Provider execution: `NOT AUTHORIZED`

This record freezes only the independently reviewed HTTPS transport. It does
not integrate the transport, create authorization, or permit provider access.

## Frozen transport identities

| Artifact | SHA-256 |
| --- | --- |
| Reviewed candidate ZIP `NFL_Historical_Market_Odds_API_Transport_0.1.3_Candidate.zip` | `51CFC998543285188C5381987C289693D488BDBC3E5A584F978B3C9C361FF26A` |
| Transport source `src/sportsmodel/nfl/historical_market_odds_api_transport.py` | `2F7885CFFA02FA4EB72C9C408A76F4A9A742DC705A391A782FFCD02F2789264A` |
| Transport tests `tests/nfl/test_historical_market_odds_api_transport.py` | `057B72FF57E8A228EBD545C3785267CEBAC411FDF15E0B685F70ADA4BC076F03` |
| Implementation document `nfl_historical_market_odds_api_transport_0.1.3.md` | `51A50B0504226365F730C205AF097EDCC7CD6690140C1F0676A2BFAA83CC85D7` |
| Integration plan `nfl_historical_market_provider_pilot_real_transport_integration_plan_0.1.3.md` | `254A5E544E74FFD0C1BC59C37EE301772A7F613B7947CB565CB326EE1F610C6C` |
| Final Claude review record `nfl_historical_market_odds_api_transport_0.1.3_claude_review.md` | `43C25BF2D33FD0DD23EF6DCEEE88BDC1B83E5D98557FFB6D2A3989DDDBDA9ACF` |

## Frozen base identities

| Artifact | Identity/version | SHA-256 |
| --- | --- | --- |
| Offline executor | `nfl_historical_market_provider_pilot_execution_0.1.4` | `E199D0290E45EE611F5D1FBC1C837925343E73528BCA72E7F77A85E2B8313267` |
| Base protocol | `nfl_historical_market_research_0.2.5` | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification | `nfl_historical_market_provider_pilot_spec_0.1.3` | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest | `nfl_historical_market_provider_pilot_selection_manifest_0.1.3` | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |

## Reviewed validation evidence

- transport suite: 81 passed;
- focused frozen-executor suite: 133 passed;
- full NFL suite: 653 passed; and
- offline Odds regressions: 36 passed.

The final independent Claude review records disposition
`READY_TO_FREEZE_ODDS_API_TRANSPORT`, zero CRITICAL, HIGH, or MEDIUM findings,
closure of Transfer-Encoding M-1, acceptance of deterministic exchange cleanup,
and only non-blocking LOW/NOTE observations.

## Frozen transport semantics

- HTTPS scheme, `api.the-odds-api.com`, port 443, and the historical NFL odds
  endpoint are fixed.
- System TLS certificate and hostname verification are required.
- Redirects are returned and never followed.
- Ambient proxy routing and ambient credential lookup are absent.
- Transport configuration and timeouts are immutable and identity-bound.
- The execution boundary is two phase: `prepare → live gate → send`.
- Entering `endheaders()` is the possible-send boundary.
- Content-Encoding decoding belongs to the frozen executor.
- Transfer-Encoding evidence must agree with `HTTPResponse.chunked` before bytes
  may be labeled stdlib-dechunked.
- A sent exchange exposes deterministic, idempotent `close()` and `receive()`
  continues to guarantee closure.

## Freeze and authorization boundary

Future integration requires a separately versioned, independently reviewed
successor executor implementation and explicit authorization binding. This
freeze does not implement or authorize integration.

This freeze does **not** authorize provider DNS lookup, socket creation,
provider requests, API-key or credential use, provider purchase or account
changes, credit consumption, historical odds acquisition, pilot execution,
historical market/performance joins, model evaluation or training, predictions
or betting outputs, database mutation, migrations, production changes, or MLB
changes.
