# NFL Historical-Market Pilot Execution Implementation 0.1.3 — Claude Review

Review date: `2026-10-02`

Reviewer provenance: independent Claude review supplied by project owner.
This record does not claim repository-native Claude provenance.

Reviewed candidate:
`NFL_Historical_Market_Provider_Pilot_Execution_Implementation_0.1.3_Candidate.zip`

Reviewed ZIP SHA-256:
`91613BC3EB1A82C0226F86DBE245E267368E1BB4428A7C89B68DE03BC8D96E73`

Disposition: **REVISION_REQUIRED_BEFORE_OFFLINE_EXECUTOR_FREEZE**

## Verified closures

- Package integrity passed.
- Prior MEDIUM A is closed: recovery revalidates the governed store after
  acquiring exclusive lease ownership and before its first recovery write.
- Prior MEDIUM C is closed: stable clock identity remains authorization-bound,
  while dynamic Windows phase-offset and last-sync evidence is independently
  captured and validated.

## New blocking finding

### MEDIUM — Recovery requires an incomplete send attempt

Implementation 0.1.3 required at least one current `RESERVED` or `SENT` attempt
before terminal recovery. That incorrectly rejected valid governed unmanifested
crash states after provider activity, including `RESPONSE_CAPTURED`,
`SENT_UNKNOWN`, `TERMINAL_STOP`, and all-targets-captured stores that crashed
before their final report or manifest.

The required correction is removal of only that incomplete-attempt prerequisite.
Post-lease revalidation, manifest rejection, authorization and governed-identity
validation, ledger integrity, provenance separation, and terminal non-resuming
recovery remain required. An empty `recovered_attempt_ids` list is valid.

## Non-blocking LOW/NOTE observations

Pre-first-`RESERVED` zero-provider-call crashes, recovery re-entry after a
recovery crash, torn ledger-line policy, dependency identity, dynamic clock
plausibility/freshness thresholds, exact `w32tm` source-string normalization,
locale handling, and deterministic fake-transport hooks remain explicitly
non-blocking and outside this remediation.

## Review boundary

The review did not authorize a provider credential, provider call, purchase,
credit consumption, pilot execution, historical odds acquisition,
market/performance join, model execution, database change, migration,
production change, commit, or push.
