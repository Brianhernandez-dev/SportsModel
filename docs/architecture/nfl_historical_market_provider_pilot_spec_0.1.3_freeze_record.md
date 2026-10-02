# NFL Historical-Market Provider Pilot Design 0.1.3 — Freeze Record

Freeze date: `2026-10-01`

Freeze disposition: `PILOT_DESIGN_0_1_3_FROZEN`

This record freezes the independently reviewed design and selection identities
below. It does not activate provider access or execution authority.

## Frozen identities

| Artifact | Identity/version | SHA-256 |
| --- | --- | --- |
| Base protocol | `nfl_historical_market_research_0.2.5` | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification | `nfl_historical_market_provider_pilot_spec_0.1.3` | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest | `nfl_historical_market_provider_pilot_selection_manifest_0.1.3` | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Provider feasibility evidence | `nfl_historical_market_provider_feasibility_2026-09-28` | `FAC1DB73C26753F378A01516C59F711A150DE0D1A818675245E6370FD959EA43` |
| Draft provider amendment | `nfl_historical_market_provider_amendment_0.2.5_draft` | `2B5F14CDFF53B38C7AFDF4FFD646D4D07EA327A5AAE7F5E68AAF978021B357B5` |
| Final Claude review record | `nfl_historical_market_provider_pilot_spec_0.1.3_claude_review` | `425143C22278EC5DB312EF5DE11A2B91D314455BE12311947D7277696CE32CD5` |
| Reviewed candidate ZIP | `NFL_Historical_Market_Provider_Pilot_Design_0.1.3_Candidate.zip` | `D71C1C77D58C996091A6745221436DD6FF858A2009D1A63BB8FC80CF8AC6EBC9` |

Reviewed candidate package-manifest SHA-256:
`6D928959B8AE5B3FE7FED648E10C4148B89D91169E7EA531657028381571C084`.

## Frozen population and selection

- source and eligible population SHA-256:
  `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F`;
- eligible kickoff-authority population: 1,359 games;
- kickoff-provenance failures: 0;
- frozen targets: 20; and
- distinct primary requested timestamps/requests: 20.

The selection remains outcome-blind and immutable under the pilot specification.
No target replacement, recomputation against later schedule state, or change to
canonical request bytes is authorized by this freeze.

## Pinned kickoff authority

| Artifact | Identity/version | SHA-256 |
| --- | --- | --- |
| Reconciliation package | `NFL_Kickoff_Authority_Reconciliation_0.2.0.zip` | `2422D97F2A21D9171286AD6F62D5F7D1957993476872AAD936DC627474A2D971` |
| Authority ledger | `nfl_kickoff_authority_ledger_0.2.0.jsonl` | `4A1C2962FF2526924FFA8AFC0275788B423B4848318043609BFF194C0049063D` |

The reconciliation package and authority ledger are referenced by immutable
identity and are not regenerated or altered by this freeze.

## Review disposition

The final independent Claude delta review supplied by the project owner records
reviewer disposition `READY_TO_FREEZE`, project interpretation
`READY_TO_FREEZE_PILOT_DESIGN`, and zero CRITICAL, HIGH, or MEDIUM findings. Its
four editorial/future-review notes are explicitly non-blocking and do not alter
the reviewed 0.1.3 specification or selection.

## Freeze boundary

This freeze authorizes only:

- preservation of the reviewed pilot design;
- preservation of the frozen 20-target selection; and
- future preparation of a separately reviewed and separately executed
  single-use pilot authorization satisfying Section 13 of the frozen pilot
  specification.

This freeze does **not** authorize:

- purchase or provider-account changes;
- API-key or credential use;
- provider-data calls;
- historical odds acquisition;
- provider-credit consumption;
- pilot execution;
- historical market/performance joins;
- model evaluation;
- model training or retraining;
- predictions or betting outputs;
- database mutation or migrations; or
- production or MLB production changes.

The draft provider amendment remains
`DRAFT — NOT ACTIVE — NOT ACQUISITION AUTHORITY`.

Final reference-market construction, final reference-book universe, final
executable-price policy, final `maximum_snapshot_age`, and the final
simultaneous-observation tie-break remain unresolved. Full historical
acquisition remains unauthorized.

The provider feasibility evidence, draft provider amendment, pilot design,
frozen selection, kickoff-authority reconciliation, and retained provider public
documentation remain frozen/retained evidence, not executable authority. A
future provider pilot requires a separate explicit single-use execution
authorization; this record does not create one.
