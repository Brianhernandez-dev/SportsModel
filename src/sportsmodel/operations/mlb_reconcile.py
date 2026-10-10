"""Pinned, existing-only MLB schedule reconciliation with mandatory preview.

Only game_sources insertion and approved existing game timestamp refresh. No
teams/games creation, historical data, betting, providers or workflow execution.
The normal canonical matcher is reused in read-only existing-only mode.
"""
from datetime import date
from hashlib import sha256
from pathlib import Path
import re

from sportsmodel.database.mlb_operator_guard import (
    OperatorRefusal, aware, canonical_json, digest, load_mlb_teams, positive,
    strict_json, verify_target,
)
from sportsmodel.ingest.game_matching import (
    DEFAULT_GAME_TIME_TOLERANCE, get_or_create_canonical_game,
)
from sportsmodel.ingest.mlb_game_policy import confirmed_championship_game, extract_schedule_games
from sportsmodel.ingest.mlb_schedule import update_canonical_game
from sportsmodel.ingest.team_identity import normalize_team_name


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    paths = ["operations/mlb_reconcile.py", "database/mlb_operator_guard.py",
             "operations/mlb_operator_cli.py",
             "ingest/game_matching.py", "ingest/mlb_schedule.py", "ingest/mlb_game_policy.py",
             "ingest/team_identity.py"]
    return digest({p: sha256((root / p).read_bytes()).hexdigest() for p in paths})


def _sources(value):
    if not isinstance(value, list) or not value:
        raise OperatorRefusal("Exact nonempty source-state list required")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"source_name", "external_game_id"}:
            raise OperatorRefusal("Source-state fields differ from contract")
        if item["source_name"] not in ("odds_api", "mlb_stats") or not isinstance(item["external_game_id"], str) or not item["external_game_id"]:
            raise OperatorRefusal("Only exact retained MLB/Odds source identities permitted")
        result.append((item["source_name"], item["external_game_id"]))
    if len(set(result)) != len(result):
        raise OperatorRefusal("Duplicate expected source identity")
    return sorted(result)


def validate_inputs(payload_bytes, allowlist_bytes):
    if len(payload_bytes) > 10_000_000 or len(allowlist_bytes) > 128_000:
        raise OperatorRefusal("Evidence exceeds bounded operator input size")
    allowlist = strict_json(allowlist_bytes)
    if not isinstance(allowlist, dict) or set(allowlist) != {"version", "domain", "target_date", "payload_sha256", "games"}:
        raise OperatorRefusal("Allowlist fields differ from version 1")
    if type(allowlist["version"]) is not int or allowlist["version"] != 1 or allowlist["domain"] != "MLB":
        raise OperatorRefusal("Wrong reconciliation version/domain")
    day = date.fromisoformat(allowlist["target_date"])
    if day.isoformat() != allowlist["target_date"]:
        raise OperatorRefusal("One canonical ISO target date required")
    expected_hash = allowlist["payload_sha256"]
    if not isinstance(expected_hash, str) or not re.fullmatch("[0-9a-f]{64}", expected_hash) or sha256(payload_bytes).hexdigest() != expected_hash:
        raise OperatorRefusal("Pinned raw payload SHA-256 differs")
    requested = allowlist["games"]
    if not isinstance(requested, list) or not 1 <= len(requested) <= 16:
        raise OperatorRefusal("One bounded nonempty game allowlist required")
    keys = {"game_pk", "home_team", "away_team", "expected_start", "existing_game_id",
            "current_sources", "resulting_sources"}
    for item in requested:
        if not isinstance(item, dict) or set(item) != keys:
            raise OperatorRefusal("Game allowlist fields differ from contract")
        positive(item["game_pk"]); positive(item["existing_game_id"])
        if not all(isinstance(item[k], str) and normalize_team_name(item[k]) == item[k] for k in ("home_team", "away_team")) or item["home_team"] == item["away_team"]:
            raise OperatorRefusal("Distinct canonical expected participants required")
        start = aware(item["expected_start"])
        from zoneinfo import ZoneInfo
        if start.astimezone(ZoneInfo("America/Los_Angeles")).date() != day:
            raise OperatorRefusal("Expected start outside approved Pacific date")
        before, after = _sources(item["current_sources"]), _sources(item["resulting_sources"])
        addition = ("mlb_stats", str(item["game_pk"]))
        if after != sorted(set(before) | {addition}):
            raise OperatorRefusal("Only an additive same-game MLB mapping is approved")
        if any(name == "mlb_stats" and external != str(item["game_pk"]) for name, external in before):
            raise OperatorRefusal("Conflicting approved MLB source state")
    pks = [r["game_pk"] for r in requested]
    if len(set(pks)) != len(pks) or len({r["existing_game_id"] for r in requested}) != len(requested):
        raise OperatorRefusal("Duplicate PK or split/merged expected canonical target")
    payload = strict_json(payload_bytes)
    returned = extract_schedule_games(payload, expected_date=day)
    actual = [positive(g.get("gamePk")) for g in returned]
    if sorted(actual) != sorted(pks):
        raise OperatorRefusal("Missing, duplicate, wrong or unexpected returned gamePk")
    materialized = []
    for expected in sorted(requested, key=lambda g: g["game_pk"]):
        game = next(g for g in returned if g["gamePk"] == expected["game_pk"])
        if not confirmed_championship_game(game):
            raise OperatorRefusal("Deferred/non-model/conditional/TBD event is not reconcilable")
        status = game.get("status")
        if not isinstance(status, dict) or type(status.get("startTimeTBD", False)) is not bool or status.get("startTimeTBD", False):
            raise OperatorRefusal("Unresolved or malformed event start")
        try:
            home = game["teams"]["home"]["team"]
            away = game["teams"]["away"]["team"]
            home_name, away_name = normalize_team_name(home["name"]), normalize_team_name(away["name"])
            home_id, away_id = positive(home["id"]), positive(away["id"])
        except (KeyError, TypeError, AttributeError):
            raise OperatorRefusal("Malformed oriented provider participants") from None
        if (home_name, away_name) != (expected["home_team"], expected["away_team"]):
            raise OperatorRefusal("Provider participants reversed or differ from approval")
        if aware(game.get("gameDate")) != aware(expected["expected_start"]):
            raise OperatorRefusal("Provider start differs from pinned expected start")
        materialized.append({**expected, "home_mlb_id": home_id, "away_mlb_id": away_id})
    return day, materialized


def _plan(cursor, day, requested, *, lock=False):
    states = []
    for expected in requested:
        gid = expected["existing_game_id"]
        cursor.execute("SELECT game_id,game_date,home_team_id,away_team_id,mlb_game_id FROM games WHERE game_id=%s"
                       + (" FOR UPDATE" if lock else ""), (gid,))
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise OperatorRefusal("Approved existing canonical target is missing/ambiguous")
        _, current_start, home_id, away_id, legacy_pk = rows[0]
        clubs = load_mlb_teams(cursor, (home_id, away_id), lock=lock)
        if (clubs[home_id]["name"], clubs[away_id]["name"], clubs[home_id]["mlb_team_id"], clubs[away_id]["mlb_team_id"]) != (
                expected["home_team"], expected["away_team"], expected["home_mlb_id"], expected["away_mlb_id"]):
            raise OperatorRefusal("Existing canonical/source participant orientation differs")
        start = aware(expected["expected_start"])
        from zoneinfo import ZoneInfo
        if (current_start.astimezone(ZoneInfo("America/Los_Angeles")).date() != day
                or abs(start - current_start) > DEFAULT_GAME_TIME_TOLERANCE):
            raise OperatorRefusal("Existing start outside reviewed bounded 15-minute approval")
        if legacy_pk is not None and legacy_pk != expected["game_pk"]:
            raise OperatorRefusal("Legacy MLB identity conflicts")
        # Freeze all same-date/nearby oriented competitors; never let preview
        # select a unique target while execution overlooks a changed candidate set.
        cursor.execute("""SELECT g.game_id,to_jsonb(g) FROM games g WHERE
            (g.home_team_id=%s AND g.away_team_id=%s) AND
            ((g.game_date AT TIME ZONE 'America/Los_Angeles')::date=%s
             OR g.game_date BETWEEN %s AND %s) ORDER BY g.game_id"""
            + (" FOR UPDATE OF g" if lock else ""),
            (home_id, away_id, day, start - DEFAULT_GAME_TIME_TOLERANCE, start + DEFAULT_GAME_TIME_TOLERANCE))
        candidates = cursor.fetchall()
        # Stricter incident approval: any second same-day oriented identity is
        # unresolved even if a nearby candidate would win the normal matcher.
        if len(candidates) != 1 or candidates[0][0] != gid:
            raise OperatorRefusal("Split/same-day identity requires independent disposition")
        candidate_ids = [r[0] for r in candidates]
        cursor.execute("""SELECT game_source_id,game_id,source_name,external_game_id,created_at
            FROM game_sources WHERE game_id=ANY(%s) OR (source_name='mlb_stats' AND external_game_id=%s)
            ORDER BY game_source_id""" + (" FOR SHARE" if lock else ""),
            (candidate_ids, str(expected["game_pk"])))
        source_rows = cursor.fetchall()
        if any(r[1] != gid for r in source_rows):
            raise OperatorRefusal("MLB PK is already mapped to a different canonical game")
        observed_sources = sorted((r[2], r[3]) for r in source_rows)
        if observed_sources != _sources(expected["current_sources"]):
            raise OperatorRefusal("Retained source state differs from exact approval")
        selected = get_or_create_canonical_game(cursor, source_name="mlb_stats",
            external_game_id=str(expected["game_pk"]), game_datetime=start,
            home_team_id=home_id, away_team_id=away_id,
            existing_only=True, persist_mapping=False)
        if selected != gid:
            raise OperatorRefusal("Reviewed matcher did not select the approved existing game")
        states.append({"game_pk": expected["game_pk"], "game_id": gid,
                       "snapshot": {"candidate_rows": candidates, "source_rows": source_rows, "teams": clubs},
                       "home_team_id": home_id, "away_team_id": away_id,
                       "expected_start": start.isoformat(), "current_start": current_start.isoformat(),
                       "mapping_insert": ("mlb_stats", str(expected["game_pk"])) not in observed_sources,
                       "time_refresh": current_start != start})
    return states


def preview_reconciliation(*, payload_bytes, allowlist_bytes, target, connection_factory, process_probe=None):
    day, requested = validate_inputs(payload_bytes, allowlist_bytes)
    connection = connection_factory()
    try:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        kwargs = {} if process_probe is None else {"process_probe": process_probe}
        guard = verify_target(connection, target, readonly=True, **kwargs)
        with connection.cursor() as cursor:
            plans = strict_json(canonical_json(_plan(cursor, day, requested)))
        body = {"version": 1, "domain": "MLB", "target_date": day.isoformat(),
                "target": target.artifact(), "payload_sha256": sha256(payload_bytes).hexdigest(),
                "allowlist_sha256": sha256(allowlist_bytes).hexdigest(), "guard": guard,
                "implementation_fingerprint": fingerprint(), "plans": plans}
        body["preview_sha256"] = digest(body)
        # Roundtrip gives callers the exact JSON representation used for hash binding.
        return strict_json(canonical_json(body))
    finally:
        connection.rollback()
        connection.close()


def execute_reconciliation(*, payload_bytes, allowlist_bytes, preview, approved_preview_sha256,
                           target, connection_factory, acknowledge_writes=False, process_probe=None):
    if not acknowledge_writes:
        raise OperatorRefusal("Separate exact-preview write authorization required")
    day, requested = validate_inputs(payload_bytes, allowlist_bytes)
    if not isinstance(preview, dict) or set(preview) != {"version", "domain", "target_date", "target", "payload_sha256", "allowlist_sha256", "guard", "implementation_fingerprint", "plans", "preview_sha256"}:
        raise OperatorRefusal("Preview envelope differs from contract")
    if type(preview["version"]) is not int or preview["version"] != 1 or preview["domain"] != "MLB":
        raise OperatorRefusal("Unsupported preview version/domain")
    body = {k: v for k, v in preview.items() if k != "preview_sha256"}
    if (digest(body) != approved_preview_sha256 or preview["preview_sha256"] != approved_preview_sha256
            or preview["implementation_fingerprint"] != fingerprint()
            or preview["payload_sha256"] != sha256(payload_bytes).hexdigest()
            or preview["allowlist_sha256"] != sha256(allowlist_bytes).hexdigest()
            or preview["target"] != target.artifact() or preview["target_date"] != day.isoformat()):
        raise OperatorRefusal("Code/payload/allowlist/target/preview approval differs")
    connection = connection_factory()
    committing = False
    try:
        connection.set_session(readonly=False, isolation_level="SERIALIZABLE")
        kwargs = {} if process_probe is None else {"process_probe": process_probe}
        guard = verify_target(connection, target, readonly=False, **kwargs)
        with connection.cursor() as cursor:
            plans = strict_json(canonical_json(_plan(cursor, day, requested, lock=True)))
            if canonical_json(plans) != canonical_json(preview["plans"]) or guard != preview["guard"] or fingerprint() != preview["implementation_fingerprint"]:
                raise OperatorRefusal("DB/schema/code changed after mandatory preview")
            for plan in plans:
                if plan["mapping_insert"]:
                    selected = get_or_create_canonical_game(cursor, source_name="mlb_stats",
                        external_game_id=str(plan["game_pk"]), game_datetime=aware(plan["expected_start"]),
                        home_team_id=plan["home_team_id"], away_team_id=plan["away_team_id"],
                        existing_only=True, persist_mapping=True)
                    if selected != plan["game_id"]:
                        raise OperatorRefusal("Canonical selection changed before mapping insert")
                if plan["time_refresh"]:
                    update_canonical_game(cursor, game_id=plan["game_id"], game_datetime=aware(plan["expected_start"]),
                                          home_team_id=plan["home_team_id"], away_team_id=plan["away_team_id"])
                cursor.execute("SELECT source_name,external_game_id FROM game_sources WHERE game_id=%s ORDER BY source_name,external_game_id", (plan["game_id"],))
                approved = next(item for item in requested if item["game_pk"] == plan["game_pk"])
                if cursor.fetchall() != _sources(approved["resulting_sources"]):
                    raise OperatorRefusal("Resulting source state differs from approval")
        committing = True
        connection.commit()
        committing = False
        return {"status": "complete", "preview_sha256": approved_preview_sha256,
                "game_ids": [p["game_id"] for p in plans],
                "mappings_inserted": sum(p["mapping_insert"] for p in plans),
                "times_refreshed": sum(p["time_refresh"] for p in plans)}
    except Exception:
        try:
            connection.rollback()
        except Exception:
            raise OperatorRefusal("Unknown commit/rollback state; inspect before any retry") from None
        if committing:
            raise OperatorRefusal("Unknown commit acknowledgement; inspect before any retry") from None
        raise
    finally:
        connection.close()
