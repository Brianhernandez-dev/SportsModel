# NFL Historical-Market Provider Pilot Specification 0.1.2 — Claude Review Record

Review date: `2026-10-01`

Reviewed package:
`NFL_Historical_Market_Provider_Pilot_Design_0.1.2_Candidate.zip`

Reviewed package SHA-256:
`FC21A56962BDB8165B16ECB54B76FFD45A8DC5924280A29973151FE53E64D866`

Reviewer provenance: independent Claude review supplied by project owner. The
review is not repository-native provenance; this file is the project-owner-
directed repository record of the supplied disposition and findings.

Disposition: `REVISION_REQUIRED_BEFORE_PILOT_DESIGN_FREEZE`

Severity:

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 1

## MEDIUM finding

Population-hash serialization prose was ambiguous/contradictory with the pinned
hash. The listed top-level projection order and the statement that keys at every
object level were sorted did not describe the same byte representation. Literal
all-level sorting reproduced `4D3207DD...923A`; the intended top-level projection
order with nested-object key sorting reproduced the pinned
`38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F`
and all 20 per-row hashes.

Minimum remediation:

1. distinguish normative top-level projection order from nested-key sorting;
2. pin source-field mapping;
3. align or explicitly document the selection-manifest alias; and
4. re-pin specification and manifest identity without changing selection.

Pilot specification and selection manifest 0.1.3 implement this remediation.

## LOW/NOTE findings — non-blocking

- Define the localized market-level `last_update` type/syntax boundary,
  including null, empty, non-string, malformed, and timezone-less values, while
  distinguishing whole-response undecodability.
- Permit a complete valid empty/no-data response with internally consistent
  zero-credit quota evidence without treating that fact alone as a quota-shape
  anomaly.
- State explicitly that the 1,359-game pilot-selection population does not
  define or alter the separately governed historical analytic/model population.
- Clarify that eligible 408/429/5xx retries are mechanical under existing
  `Retry-After`, execution-window, and ceiling rules, and that undecodable body
  encoding or unparseable required top-level JSON is a whole-response failure.

These LOW/NOTE clarifications do not alter pilot selection, authorization,
retry classes, ceilings, timestamp authority, or downstream governance.

This record does not authorize provider access, purchase, acquisition,
persistence, normalization, database or migration changes, joining, modeling,
production action, commit, or push.
