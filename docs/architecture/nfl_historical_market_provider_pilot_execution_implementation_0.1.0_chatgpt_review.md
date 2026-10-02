# NFL Historical-Market Pilot Execution Implementation 0.1.0 — ChatGPT Review

Review date: `2026-10-01`

Reviewer provenance: ChatGPT PM/technical review supplied by project owner.
This record does not claim repository-native ChatGPT provenance.

Reviewed candidate:
`NFL_Historical_Market_Provider_Pilot_Execution_Implementation_0.1.0_Candidate.zip`

Reviewed ZIP SHA-256:
`0CF9C4CE6550CC6A8C3E19F4CFDE428AC73BCA83A2F4B1D88A4B3D91A900C03C`

Disposition: **REVISION_REQUIRED_BEFORE_SECONDARY_REVIEW**

## Verified strengths

- Package and internal manifest integrity passed.
- The packaged focused suite was independently rerun: `82 passed`.
- Core parser, state-machine, quota, timestamp, secret-redaction, immutable-
  evidence, and evidence-manifest behavior materially passed review.
- A real network/provider transport was intentionally absent and remained
  unauthorized.

## Findings requiring remediation

### HIGH — Crash/restart and prior accounting lifecycle

`AttemptLedger.recover_incomplete()` existed but was not integrated into an
executor recovery lifecycle. The existence-only lock could remain after a hard
crash, the single-use authorization/store could not simply be reopened, and a
fresh authorization/store could restart attempt and conservative-credit counts
without predecessor-run accounting.

### HIGH — Runtime identities were asserted rather than measured

Repository HEAD/cleanliness, implementation identity, credential identity, and
clock identity were supplied by the caller and compared with the authorization,
but were not established against the actual running environment or injected
credential/transport.

### MEDIUM — Authorization mutation at final attempt

Authorization bytes were checked before attempts but not after the final
provider boundary or before final report/manifest acceptance. Mutation during
the twentieth synthetic exchange could therefore still yield a procedural
`PILOT_PROVIDER_EVIDENCE_SUFFICIENT` result.

### MEDIUM — Runtime provenance incomplete

The pre-reservation evidence lacked the complete frozen Section 9 provenance:
OS synchronization source/status, offset evidence, monotonic timer identity,
runtime/dependency identity, and timezone-database identity.

### MEDIUM — Initial evidence store not required to be dedicated

Initialization accepted an arbitrary pre-existing directory. Unrelated content
could consequently be swept into the evidence manifest instead of failing
closed.

## Review boundary

The review did not authorize a provider credential, account action, purchase,
provider call, credit consumption, pilot execution, historical odds acquisition,
market/performance join, model work, database change, migration, production
change, commit, or push. A later real transport requires separate implementation,
review, identity binding, and authorization.
