# NFL Historical-Market Real-Transport Integration Plan 0.1.2

Status: **DESIGN ONLY — INTEGRATION AND PROVIDER EXECUTION NOT AUTHORIZED**

## Purpose

This document defines the minimum future integration sequence for the candidate
`nfl_historical_market_odds_api_transport_0.1.2`. It does not modify or activate
the frozen offline executor 0.1.4 and creates no provider authority.

## Required execution sequence

A separately reviewed successor executor must enforce exactly this order:

1. perform the existing live authorization/window gate;
2. durably reserve the attempt;
3. retain immutable request evidence;
4. repeat the existing live authorization gate;
5. call `transport.prepare()` with no request or credential;
6. perform the live authorization/window gate again after preparation;
7. if that gate fails, close the prepared connection, send zero provider HTTP
   request bytes, and terminalize under reviewed authorization semantics;
8. otherwise call `prepared.send(request, credential)`;
9. append `SENT` immediately after successful completion of the send boundary;
10. continue the existing receive, evidence, and quota logic.

The successor executor—not the transport—owns both the clock and post-prepare
gate. The transport must not receive an authorization object, clock, or generic
caller callback. No production combined prepare/send shortcut or generic
transport-injection path is permitted.

## Identity and admission

Integration must require the exact reviewed concrete transport type and runtime
identity. Authorization, runtime provenance, run identity, and the evidence
manifest must pin the module SHA-256, implementation identity, endpoint and
policy payload, immutable timeouts, transfer-framing policy, Content-Encoding
ownership, and `PREPARE_THEN_REVALIDATE_THEN_SEND` semantics. Subclasses,
wrappers, arbitrary factories, alternate endpoints, and unbound configuration
must fail closed.

## Failure and response mapping

DNS/TCP/TLS and timeout failures during `prepare()` are provable pre-send.
Request validation and local `putrequest`/`putheader` buffering failures during
`send()` remain pre-send. Entering `endheaders()` remains possible send. Reset,
read timeout, incomplete body, and unsupported/ambiguous transfer framing remain
conservative post-send outcomes. No retry policy belongs in the transport.

The transport continues to return complete, transfer-validated entity bytes
with immutable raw headers. The successor executor must continue using its
reviewed `decode_application_body()` function; no double-decoding adapter is
needed.

## DNS operational note

The standard socket connect timeout does not strictly bound platform DNS
resolution because `getaddrinfo()` occurs first. This bounded design introduces
no custom resolver, thread, or subprocess. The mandatory post-prepare live gate
prevents delayed preparation from permitting HTTP transmission outside the
authorization window. A hard DNS wall-clock bound remains an operational
LOW/NOTE for later review.

## Required future review

Before integration, independently review and hash the exact transport source,
tests, runtime identity, prepared-object lifecycle, successor executor diff,
and authorization failure terminalization. Repeat offline and cross-sport
regressions. Real provider execution additionally requires a separate explicit
single-use execution authorization. This plan grants none of those authorities.
