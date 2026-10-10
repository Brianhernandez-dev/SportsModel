"""Explicit endpoint/schema/domain guard for separately authorized MLB tools.

No ambient connection, environment discovery or privileged storage query. Native
production identity is corroborated by an application-role backend/process chain;
isolated verification identity uses an explicitly pinned PostgreSQL system ID.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import subprocess
import shlex

from sportsmodel.ingest.mlb_game_policy import MLB_CLUB_NAMES
from sportsmodel.ingest.team_identity import normalize_team_name


class OperatorRefusal(ValueError):
    """An unproven target, scope or approval must not become a live operation."""


def aware(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, AttributeError, ValueError):
        raise OperatorRefusal("Expected an aware ISO timestamp") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise OperatorRefusal("Expected an aware ISO timestamp")
    return result.astimezone(timezone.utc)


def positive(value):
    if type(value) is not int or value <= 0:
        raise OperatorRefusal("Expected a positive integer")
    return value


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=lambda v: v.isoformat())


def digest(value):
    return sha256(canonical_json(value).encode()).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise OperatorRefusal("Duplicate JSON field")
            result[key] = value
        return result
    def nonfinite(_):
        raise OperatorRefusal("Nonfinite JSON value")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


@dataclass(frozen=True)
class OperatorTarget:
    host: str
    port: int
    database: str
    server_address: str
    server_port: int
    postmaster_started_at: str
    identity_kind: str
    system_identifier: str | None = None
    domain: str = "MLB"
    migration_boundary: int = 33

    def __post_init__(self):
        if self.domain != "MLB" or type(self.migration_boundary) is not int or self.migration_boundary != 33:
            raise OperatorRefusal("Expected exact MLB / migration 033 domain")
        try:
            host = ipaddress.ip_address(self.host)
            ipaddress.ip_address(self.server_address)
        except ValueError:
            raise OperatorRefusal("Literal endpoint addresses required; no ambiguous aliases") from None
        if not host.is_loopback or not self.database or not isinstance(self.database, str):
            raise OperatorRefusal("Explicit local database endpoint required")
        for port in (self.port, self.server_port):
            if type(port) is not int or not 0 < port < 65536:
                raise OperatorRefusal("Invalid endpoint port")
        aware(self.postmaster_started_at)
        if self.identity_kind == "native":
            if (self.database != "sportsmodel" or self.port != 5432 or self.server_port != 5432
                    or self.host != "127.0.0.1" or self.server_address != "127.0.0.1"
                    or self.system_identifier is not None):
                raise OperatorRefusal("Native production target contract differs")
        elif self.identity_kind == "isolated":
            if self.database.casefold() == "sportsmodel" or self.port == 5432:
                raise OperatorRefusal("Isolated verification must not address production")
            if not isinstance(self.system_identifier, str) or not self.system_identifier.isdigit():
                raise OperatorRefusal("Pinned isolated system identity required")
        else:
            raise OperatorRefusal("Unrecognized target identity kind")

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise OperatorRefusal("Target must be an explicit object")
        try:
            return cls(**value)
        except TypeError:
            raise OperatorRefusal("Target fields differ from contract") from None

    def artifact(self):
        return asdict(self)


def native_process_proof(backend_pid):
    """Read-only Windows observation, never service/task execution or alteration."""
    pid = positive(backend_pid)
    script = f"""
$ErrorActionPreference='Stop'
$svc=Get-CimInstance Win32_Service -Filter "Name='SportsModelPostgreSQL16'"
$backend=Get-CimInstance Win32_Process -Filter "ProcessId={pid}"
$master=Get-CimInstance Win32_Process -Filter "ProcessId=$($backend.ParentProcessId)"
$listeners=@(Get-NetTCPConnection -State Listen -LocalPort 5432 | Where-Object LocalAddress -EQ '127.0.0.1')
[ordered]@{{service_name=$svc.Name;state=$svc.State;service_pid=$svc.ProcessId;service_path=$svc.PathName;
 backend_pid=$backend.ProcessId;postmaster_pid=$master.ProcessId;postmaster_parent=$master.ParentProcessId;
 listeners=@($listeners | Select-Object LocalAddress,LocalPort,OwningProcess)}} | ConvertTo-Json -Depth 6
"""
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script],
                                capture_output=True, check=True, timeout=15, text=True)
        return strict_json(result.stdout)
    except Exception:
        raise OperatorRefusal("Native process identity could not be proven") from None


def validate_native_proof(value, backend_pid):
    try:
        tokens = [v.strip('"') for v in shlex.split(value["service_path"], posix=False)]
        exact_service = (tokens[0].casefold() == r'D:\PostgreSQL\16\server\bin\pg_ctl.exe'.casefold()
                         and tokens.count("-D") == tokens.count("-N") == 1
                         and tokens[tokens.index("-D") + 1].casefold() == r'D:\PostgreSQL\16\data'.casefold()
                         and tokens[tokens.index("-N") + 1] == "SportsModelPostgreSQL16")
        valid = (value["service_name"] == "SportsModelPostgreSQL16"
                 and value["state"] == "Running" and value["backend_pid"] == backend_pid
                 and value["postmaster_parent"] == value["service_pid"]
                 and exact_service
                 and len(value["listeners"]) == 1
                 and value["listeners"][0]["OwningProcess"] == value["postmaster_pid"]
                 and value["listeners"][0]["LocalAddress"] == "127.0.0.1"
                 and value["listeners"][0]["LocalPort"] == 5432)
    except (KeyError, TypeError, ValueError, IndexError):
        valid = False
    if not valid:
        raise OperatorRefusal("Ambiguous native backend/listener/service identity")


def migration_reference():
    root = Path(__file__).resolve().parents[3]
    paths = sorted((root / "database/migrations").glob("*.sql"))
    if [int(p.name[:3]) for p in paths] != list(range(1, 34)):
        raise OperatorRefusal("Reviewed migration inventory differs from 001-033")
    return tuple((int(p.name[:3]), p.name,
                  sha256(p.read_text(encoding="utf-8-sig").encode()).hexdigest()) for p in paths)


def verify_target(connection, target, *, readonly, process_probe=native_process_proof):
    if not isinstance(target, OperatorTarget):
        raise OperatorRefusal("Explicit validated MLB target required")
    # libpq's actual client endpoint is distinct from a container's server port.
    if (connection.info.host != target.host or connection.info.port != target.port
            or connection.info.dbname != target.database):
        raise OperatorRefusal("Connected client endpoint differs from approved target")
    with connection.cursor() as cursor:
        cursor.execute("""SELECT current_database(),host(inet_server_addr()),inet_server_port(),
            pg_postmaster_start_time(),pg_backend_pid(),current_setting('server_version_num'),
            current_setting('transaction_read_only'),current_setting('transaction_isolation')""")
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise OperatorRefusal("Ambiguous connected database identity")
        db, address, port, started, backend, version, read_only, isolation = rows[0]
        if (db != target.database or address != target.server_address or port != target.server_port
                or started != aware(target.postmaster_started_at) or int(version) // 10000 != 16
                or read_only != ("on" if readonly else "off")
                or isolation != ("repeatable read" if readonly else "serializable")):
            raise OperatorRefusal("Server endpoint/epoch/read-only/isolation identity differs")
        if target.identity_kind == "native":
            validate_native_proof(process_probe(backend), backend)
        else:
            cursor.execute("SELECT (pg_control_system()).system_identifier::text")
            if cursor.fetchall() != [(target.system_identifier,)]:
                raise OperatorRefusal("Isolated PostgreSQL system identity differs")
        cursor.execute("SELECT version,filename,checksum FROM schema_migrations ORDER BY version")
        observed = tuple((v, name, checksum.strip()) for v, name, checksum in cursor.fetchall())
        if observed != migration_reference():
            raise OperatorRefusal("Migration inventory/checksums differ from exact 001-033")
    return {"target": target.artifact(), "migration_fingerprint": digest(observed)}


def load_mlb_teams(cursor, team_ids, *, lock=False):
    """Positive franchise/source evidence, not a date-only shared games selector."""
    ids = tuple(sorted(set(positive(i) for i in team_ids)))
    cursor.execute("""SELECT t.team_id,t.team_name,s.external_team_id,s.baseball_team_source_id
        FROM teams t LEFT JOIN baseball_team_sources s ON s.team_id=t.team_id AND s.source_name='mlb_stats'
        WHERE t.team_id=ANY(%s) ORDER BY t.team_id,s.baseball_team_source_id"""
        + (" FOR SHARE OF t" if lock else ""), (list(ids),))
    rows = cursor.fetchall()
    result = {}
    for canonical_id in ids:
        selected = [row for row in rows if row[0] == canonical_id]
        if len(selected) != 1:
            raise OperatorRefusal("Missing/ambiguous authoritative MLB team identity")
        _, name, external, _ = selected[0]
        if (not isinstance(external, str) or not external.isdigit()
                or int(external) not in MLB_CLUB_NAMES
                or normalize_team_name(name) != MLB_CLUB_NAMES[int(external)]):
            raise OperatorRefusal("Non-MLB or conflicting franchise domain")
        result[canonical_id] = {"team_id": canonical_id, "name": normalize_team_name(name),
                                "mlb_team_id": int(external), "source_row_id": selected[0][3]}
    if lock:
        cursor.execute("SELECT baseball_team_source_id FROM baseball_team_sources WHERE team_id=ANY(%s) AND source_name='mlb_stats' ORDER BY baseball_team_source_id FOR SHARE", (list(ids),))
        cursor.fetchall()
    return result


class SnapshotConnection:
    """Reuse one guarded snapshot for repository functions that call close()."""
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return self.connection.cursor()

    def close(self):
        pass
