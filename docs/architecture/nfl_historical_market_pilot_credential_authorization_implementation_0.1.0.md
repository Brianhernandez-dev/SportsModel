# NFL Pilot Credential Establishment and Pre-Authorization Builder — Safety Revision 0.1.1

Status: **IMPLEMENTATION CANDIDATE — INDEPENDENT REVIEW REQUIRED — NO PROVIDER EXECUTION**

Date: 2026-10-07. Source baseline: `729b1cfa23fdb1494fae9420834601b7b92b8ca1`,
`main`, recorded origin/main equal, ahead/behind 0/0. Revision preflight found
exactly the existing three untracked candidate files; no staged/tracked changes.
This uncommitted design record retains its 0.1.0 filename; revised builder and
candidate schema identities are 0.1.1. Credential identity schema stays 0.1.0.
No frozen source, historical document, MLB configuration, migration or task is changed.

## Credential boundary

New module: `src/sportsmodel/nfl/historical_market_pilot_authorization.py`.
Explicit actions only: `establish-credential`, `verify-credential`,
`build-candidate`, `validate-candidate`. No execute/activate/live command.

The owner reports a dedicated The Odds API 20K subscription with its own
20,000-credit meter, historical entitlement and a key distinct from MLB.
These are owner-supplied account facts, not independently queried provider facts.
No real NFL key is available to Codex, requested or used in this task.

Credential entry uses only Python getpass with its echo-fallback warning promoted
to an error BEFORE fallback input. It constructs the frozen SecretCredential
in memory and reuses its fingerprint/domain separation unchanged:
`SPORTSMODEL_ODDS_CREDENTIAL_V1\\0`. No second fingerprint algorithm exists.
A later interactive verification compares the fingerprint in constant time;
it returns no credential object and does not instantiate an executor.

No dotenv/database/provider wiring, environment-value lookup, registry, argv
key option, existing config, log or MLB secret source is used. In particular
`D:/SportsModel/.env`, `ODDS_API_KEY` and `SPORTSMODEL_ENV_FILE` are excluded:
the dedicated subscription must not accidentally use or change MLB's identity.

Only the public schema `nfl_pilot_dedicated_credential_identity_0.1.0` is retained:

- identity and uppercase frozen fingerprint;
- quota mode exactly DEDICATED_CREDENTIAL;
- provider The Odds API, subscription 20K, independent meter 20000;
- historical-entitlement confirmation and explicit non-secret verification reference.

Shape and scalar encoding are strict; extra fields, shared quota mode,
wrong labels/fingerprints, numeric substitutes for boolean values and noncanonical
JSON are rejected. Existing artifacts are never overwritten.

Proposed versioned label contract:
`nfl-historical-market-pilot:dedicated-20k:<owner-selected-alias>`.
Alias: starts with lowercase letter, at most 32 lowercase letters/digits/
underscore/hyphen. It identifies the dedicated subscription, never a key.
No actual alias was chosen or real artifact created. This documented schema/
namespace is a review candidate, not an irreversible convention silently activated.
Verification references are non-secret bounded identifier tokens.

Plaintext exists only during getpass/frozen fingerprint derivation. References
are cleared in finally; no plaintext is returned, logged or persisted.
Python immutable strings cannot be guaranteed zeroized. Prompt failures and
CLI errors are sanitized; rejected argv is not echoed. A key accidentally pasted
into public label/reference metadata fails before retention (raw/encoded checks).

## Storage and CLI boundary

Public JSON input/output must be absolute, directly under a separately chosen
`NFL_Historical_Market_Pilot` directory OUTSIDE the repository. Filenames are
bounded safe JSON names; UNC/device paths, mapped/non-fixed Windows drives,
symlinks/junctions and repo/.env paths are refused before resolution/reading.
Future operator must separately approve that directory's separation
from production/evidence stores. No such production directory is created here.

Creation reuses frozen exclusive/fsynced writes; existing paths fail. Partial
I/O artifacts may remain after failure and are not silently deleted or overwritten.
Candidate filename is `candidate-<explicit UUID4>.json`; requested evidence-store
identity is exactly `<public artifact directory>/evidence/<UUID4>` and must be
new/non-existing. Builder does not create that evidence store, lease, ledger or run.

Ordinary invocation without an explicit supported action only displays/refuses
arguments. Credential commands require later human interaction; they were exercised
only using synthetic private getpass fixtures. Help is non-executing:
`python -m sportsmodel.nfl.historical_market_pilot_authorization --help`.
There is deliberately no real credential/authorization-generation example.
Successful establish-credential, build-candidate and validate-candidate commands
report the validated public artifact path and its SHA-256. Reporting remains
inside the sanitized CLI boundary; plaintext keys and credential values are
never printed. Verify-credential remains a non-executing equality check.

## Authorization-candidate construction and read-only validation

A caller supplies secret-free CandidateRequest fields (no defaults for policy):

- UUID4 candidate ID for artifact identity ONLY, never an authorization ID;
- approved HEAD and expected Python/dependency/tzdata/clock/monotonic identities;
- dedicated evidence-store path and retained kickoff ZIP path;
- explicit connect/read timeouts and ClockPolicy (below).

CLI reads an explicitly designated canonical public request JSON with these exact
dataclass fields, nested clock_policy, and path strings. No key field or
ambient fallback is accepted. Public credential artifact is a separate input.
Activation metadata is not accepted by CandidateRequest or request JSON.

Builder verifies frozen source/protocol/spec/selection/readiness identities,
retained kickoff ZIP and exact ledger hashes, and the frozen 20-target loader/
population declarations. No reselection, population rebuild or provider query.
The exact frozen IntegratedConfig/transport identity payload is used; transport
objects are inspected only for identity, never prepared or sent. Actual frozen
LocalRuntimeProvenanceInspector/integrated inspection checks root, clean HEAD,
implementation/config, Python/dependency/tzdata, source/status, clock/monotonic,
concrete transport and inspector against the explicitly requested identities.
No public runtime/probe/transport override is added.

Construction rechecks frozen files and credential bytes, remeasures immediately
before exclusive output, and refuses mismatch, backward observation chronology,
dirty tree, existing candidate/store or changed trust-store policy.
No execution window is proposed or retained. Admission is NOT performed. It binds exact
20 primary / 20 retry / 40 total attempts / 10 conservative credits per attempt /
400 credits, DEDICATED_CREDENTIAL, initial-only/no continuation and all component/
kickoff/configuration/credential identities.

Output is an envelope `nfl_pilot_pre_authorization_candidate_0.1.1` with
`execution_authorized=false`, explicit NOT EXECUTION AUTHORITY status,
nested admission-INCOMPLETE `reviewed_bindings`, configuration, policy, builder
source hash, credential artifact hash and measured provenance.
`authorization_candidate` and the complete authorization-shaped generator are
removed. This remediates the review's HIGH: the prior envelope rejected as a whole,
but its nested object could be directly extracted into loader-ready authority.
Outer-envelope rejection and a false flag were insufficient; neither is the
new safety boundary.

The exact frozen integrated loader contract (source lines 315-411) requires
`components`, `protocol`, `pilot_spec`, `selection_manifest`, `kickoff_authority`,
`configuration_sha256`, `implementation`, `repository`, `credential`,
`evidence_store_root`, `target_ids`, `ceilings`, `clock_identity`, `runtime_mode`,
`execution_policy`, plus these FIVE activation-only fields, ALL deliberately
omitted from every candidate object and builder request:

| Omitted exact field | Why activation-only |
| --- | --- |
| `authorization_id` | Unique single-use execution identity, not candidate UUID |
| `authorizer_reference` | Explicit owner execution authority, not policy review reference |
| `authorized_at` | Timestamp of the separately authorized activation decision |
| `window_start` | Prospectively requested execution start, not a measurement timestamp |
| `window_end` | Prospectively requested execution expiry |

The frozen core loader (lines 1030-1127) requires the same top-level fields except
`components`. Both require the same five activation metadata fields, strict aware
timestamp chronology and, for execution, an active half-open window.

`activation_requirements` lists missing field NAMES and the separate-review
requirement only; it supplies no authority values, dummy IDs, authorizers,
authorization timestamps or future active windows. Recursive production checks
before writing AND during validation prohibit any of those five dictionary keys
at any depth, including null placeholders, and explicitly reject an admission-
complete dictionary under either exact source-pinned loader contract.
`measured_at` is provenance only; no mapping to `authorized_at` is implemented.
Thus neither direct extraction nor flattening/combining existing candidate fields
can supply the missing activation values. Arbitrary edits that introduce real
authority are a separate activation action, not extraction of this candidate.
No flat execution authorization, placeholder authority or activation command exists.

Read-only validate-candidate rechecks canonical bytes, exact schema/configuration/
ceilings/targets/components/credential/policy/provenance, source hashes and fresh
host gates. It refuses activation fields, complete nested objects, tampering,
future observation timestamps or inputs changed during validation;
returns only artifact SHA, never an executor or execution approval.
Serialization uses the frozen canonical UTF-8/ordinal-key/LF routine. Reproducibility
means identical explicit inputs AND identical measured observations/timestamp;
candidate IDs are supplied; observation timestamps are measured, not authorization.

## Future activation contract — NOT IMPLEMENTED

Candidate → separately reviewed and explicitly authorized activation → all five
missing authority fields supplied → immutable real single-use authorization.
A future activation implementation must verify the reviewed candidate/hash,
remeasure the approved clean current revision/runtime, verify credential identity,
approve prospective clock/launch/residual-risk policy, issue a NEW unique
authorization_id, retain the authorizer_reference and actual authorized_at, and
bind the exact requested UTC execution window. It must retain all frozen bindings,
ceilings, immutable/no-continuation/single-use safeguards and Section 13 gates.
It requires its own independent review and explicit owner authorization.
No API or CLI in this milestone performs activation, produces these missing
fields, constructs a keyed executor or contacts the provider.

## Clock/source and launch policy

ClockPolicy REQUIRES a prospective approval reference and positive integer limits:

- max_phase_offset_ms: absolute phase offset, unit-normalized with Decimal;
- max_sync_age_seconds: sync age in [0, limit], future timestamps rejected;
- max_measurement_seconds: each actual probe bounded by monotonic elapsed time;
- max_wall_clock_step_ms: allowed wall/monotonic duration discrepancy.

No numerical production thresholds are selected or purported approved here.
Synthetic test limits are fixtures only. Human/reviewer acceptance of real
prospective values is still required; a reference string is not proof of authority.

Accepted source is pinned EXACTLY to `time.windows.com,0x9`, synchronized status.
Naive Windows timestamps require local `tzutil /g` identity Pacific Standard Time
and America/Los_Angeles conversion; ambiguous DST folds/gaps fail closed.
Aware timestamps normalize to UTC. Locale/timezone failures refuse construction.
No resync or remote time probe is performed.

BUILDER / LAUNCH POLICY: either SSL_CERT_FILE or SSL_CERT_DIR present by NAME
causes refusal; values are UNREAD, not cleared or modified. Default frozen TLS
semantics are unchanged. Builder policy is a snapshot construction/validation
gate, NOT a claim of continuous enforcement by the frozen executor.

## Validation and remaining gates

New focused suite covers interactive entry, echo fallback and failure sanitization,
frozen fingerprints, no ambient lookup, strict dedicated shape, wrong credential,
non-retention, no overwrite, all candidate bindings/tampering, dirty/runtime/source
mismatches, clock units/limits/future/stale/DST/step/deadline, non-executing CLI,
public path/SHA output and structural rejection by frozen admission.
Tests use ONLY TEST_KEY_DO_NOT_SEND and October 1 synthetic observation clocks,
with explicit network/DNS/socket/provider-prepare/executor/database guards.
No production injection or frozen test modification is used.

Dedicated exploit regression builds a candidate, independently serializes its
reviewed_bindings and calls the frozen integrated loader: identity/binding checks
pass but missing authorization metadata rejects it, with active-window checking
both enabled and disabled. Every recursively extracted dictionary/list is also
serialized and rejected by BOTH frozen loaders. Exact required-field sets are
tested against both loader ASTs; guard tests reject all five keys even as null
values deeply nested in arrays. Every extracted object is sentinel-plaintext-free.

Revised focused result: 95 passed. Required frozen/odds/full-NFL reruns and final
checks are reported with exact results in the completion report; previous
79/271/36/789 counts refer to the pre-revision candidate, not this revision.
Commands run through repository .venv Python -B and guarded pytest.main(..., -q,
-p no:cacheprovider), disabling dotenv and plugin autoload BEFORE collection.
Exact invocation/output is retained in this task's tool history, not a newly
exported review package. No frozen source or test expectation is changed to pass
the revised safety tests.

Before any real pilot: independently review/freeze this implementation; approve
the actual public identity/storage and prospective policy/window; separately
authorize a HUMAN real-key establishment action; review retained residual risks;
remeasure an approved clean current revision; and separately authorize/implement
the execution boundary and single-use authority satisfying pilot spec Section 13.
The dirty candidate working tree intentionally cannot pass production builder
gates; tests use private synthetic host evidence, not a development bypass.
No future runner was necessary or added; current API cannot return a keyed executor.

No real credential read/fingerprint, provider login/DNS/socket/request, credit
consumption, purchase, provider acquisition, real authorization, real pilot,
join/model/prediction/betting workflow, DB/migration/MLB/task/service change,
commit or push occurs in this task. Production health/applied DB state remains
unverified. Frozen draft amendment remains NOT ACTIVE / NOT ACQUISITION AUTHORITY.
