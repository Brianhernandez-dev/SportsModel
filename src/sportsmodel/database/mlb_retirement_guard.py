"""Explicit exact035 target guard; original034 operator contract is untouched."""
from dataclasses import asdict,dataclass
from sportsmodel.database.mlb_operator_guard import (
    OperatorTarget as Target034,OperatorRefusal,aware,positive,canonical_json,digest,
    strict_json,load_mlb_teams,native_process_proof,validate_native_proof,SnapshotConnection,
)
from sportsmodel.database.mlb_retirement_repository import migration_reference,verify_capabilities


@dataclass(frozen=True)
class OperatorTarget:
    host:str
    port:int
    database:str
    server_address:str
    server_port:int
    postmaster_started_at:str
    identity_kind:str
    system_identifier:str|None=None
    domain:str='MLB'
    migration_boundary:int=35

    def __post_init__(self):
        if self.domain!='MLB' or type(self.migration_boundary) is not int or self.migration_boundary!=35:
            raise OperatorRefusal('Exact MLB035target required')
        fields=asdict(self);fields['migration_boundary']=34
        Target034(**fields)

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,dict):raise OperatorRefusal('Explicit target object required')
        try:return cls(**value)
        except TypeError:raise OperatorRefusal('Target fields differ') from None

    def artifact(self):return asdict(self)


def verify_target(connection,target,*,readonly,process_probe=native_process_proof):
    if not isinstance(target,OperatorTarget):raise OperatorRefusal('Validated035target required')
    if (connection.info.host,connection.info.port,connection.info.dbname)!=(target.host,target.port,target.database):
        raise OperatorRefusal('Client endpoint differs')
    with connection.cursor() as cursor:
        cursor.execute("""SELECT current_database(),host(inet_server_addr()),inet_server_port(),
            pg_postmaster_start_time(),pg_backend_pid(),current_setting('server_version_num'),
            current_setting('transaction_read_only'),current_setting('transaction_isolation')""")
        rows=cursor.fetchall()
        if len(rows)!=1:raise OperatorRefusal('Ambiguous target')
        db,address,port,started,backend,version,read_only,isolation=rows[0]
        if (db,address,port,started)!=(target.database,target.server_address,target.server_port,aware(target.postmaster_started_at)):
            raise OperatorRefusal('Server epoch/endpoint differs')
        if int(version)//10000!=16 or read_only!=('on' if readonly else 'off') or isolation!=('repeatable read' if readonly else 'serializable'):
            raise OperatorRefusal('Server/read-only/isolation differs')
        if target.identity_kind=='native':validate_native_proof(process_probe(backend),backend)
        else:
            cursor.execute('SELECT (pg_control_system()).system_identifier::text')
            if cursor.fetchall()!=[(target.system_identifier,)]:raise OperatorRefusal('Isolated system identity differs')
        cursor.execute('SELECT version,filename,checksum FROM schema_migrations ORDER BY version')
        observed=tuple((v,n,h.strip()) for v,n,h in cursor.fetchall())
        if observed!=migration_reference():raise OperatorRefusal('Exact001-035checksums required')
        verify_capabilities(cursor)
    return dict(target=target.artifact(),migration_fingerprint=digest(observed))
