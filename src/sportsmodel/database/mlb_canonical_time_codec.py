"""MLB036 canonical framed codec; hashes identify bytes, not caller authority."""
from datetime import date, datetime, timezone
from hashlib import sha256
import re

MAX_BODY = 16 * 1024 * 1024
MAX_CHILDREN = 100_000
MAX_DEPTH = 32
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class CodecRefusal(ValueError):
    """An unsupported value cannot be coerced into an authority fingerprint."""


class Unsigned64(int):
    """Explicit xid8/unsigned integer type; ordinary integers remain signed."""


TIMESTAMP_FIELDS = frozenset(('old_start','new_start','game_date','gameDate','subject_start','recorded_at',
    'available_at','cutoff_time','postmaster_started_at','created_at','updated_at','snapshot_time',
    'started_at','completed_at','last_synced_at','observed_at','bookmaker_updated_at','market_updated_at','provider_commence_time',
    'request_commence_time_from','request_commence_time_to','request_started_at','response_received_at'))
DIGEST_FIELDS = frozenset(('profile','schema_capability_profile','ledger034','ledger035','projection_digest',
    'fence_digest','correction_state_fingerprint','identity034_digest','identity035_digest','receipt_body_sha256','artifact_sha256'))
BUSINESS_FIELDS = frozenset(('identity','history','teams','pitching','markets','legacy','observations','team_sources','player_sources',
    'team_identities','player_identities','ingestion_runs','sportsbooks','book_sources','canonical_corrections'))


def business_value(snapshot):
    """Typed mirror of the server's bounded business-state framing projection.

    The server emits NUMERIC line values as exact decimal strings and explicit UTC
    legacy timestamps. Its retained historical game_date is a DATE, not an instant.
    No float conversion or mutation of the original snapshot is permitted here.
    """
    if type(snapshot) is not dict or set(snapshot) != BUSINESS_FIELDS:
        raise CodecRefusal('Exact business snapshot fields required')
    if type(snapshot['history']) is not list:
        raise CodecRefusal('Business history list required')
    projected=dict(snapshot)
    history=[]
    for row in snapshot['history']:
        if type(row) is not dict or 'game_date' not in row or 'official_date' in row:
            raise CodecRefusal('Exact historical DATE projection required')
        mapped=dict(row)
        mapped['official_date']=mapped.pop('game_date')
        history.append(mapped)
    projected['history']=history
    return semantic_value(projected)


def semantic_value(value, *, field_name='', depth=0):
    """Construct reviewed typed macro values from strictly parsed JSON.

    Callers must parse raw JSON with duplicate-key rejection before this boundary;
    a dict (like PostgreSQL JSONB) cannot preserve duplicate-key evidence.
    """
    if depth > MAX_DEPTH:
        raise CodecRefusal('Depth limit exceeded')
    if value is None:
        return None
    if field_name in TIMESTAMP_FIELDS:
        if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-5][0-9])',value):
            raise CodecRefusal('Strict semantic timestamp required')
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.utcoffset() is None:raise ValueError()
            return parsed
        except (ValueError,OverflowError):
            raise CodecRefusal('Strict semantic timestamp required') from None
    if field_name in ('officialDate','official_date','active_from','active_through'):
        if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
            raise CodecRefusal('Strict official date required')
        try:date.fromisoformat(value)
        except ValueError:raise CodecRefusal('Strict official date required') from None
        return value
    if field_name in ('writer_xid8','issuer_xid8'):
        if type(value) not in (str,int) or not re.fullmatch(r'[0-9]+',str(value)) or not 0<=int(value)<2**64:
            raise CodecRefusal('Strict semantic xid8 required')
        return Unsigned64(value)
    if field_name in DIGEST_FIELDS or field_name.endswith('_sha256'):
        if type(value) is not str or not re.fullmatch(r'[0-9a-f]{64}',value):
            raise CodecRefusal('Strict semantic digest required')
        return bytes.fromhex(value)
    if field_name=='audit_bytes':
        if type(value) is not str or not re.fullmatch(r'(?:[0-9a-f]{2})+',value):
            raise CodecRefusal('Strict semantic audit frame required')
        return bytes.fromhex(value)
    if type(value) is dict:
        if len(value)>MAX_CHILDREN or any(type(k) is not str for k in value):
            raise CodecRefusal('Strict semantic object required')
        return {k:semantic_value(v,field_name=k,depth=depth+1) for k,v in value.items()}
    if type(value) is list:
        if len(value)>MAX_CHILDREN:raise CodecRefusal('Cardinality limit exceeded')
        return [semantic_value(v,field_name='audit_bytes' if field_name=='audits' else '',depth=depth+1) for v in value]
    # Enforce primitive support/overflow, even if the caller only constructs a value.
    encode(value)
    return value


def _frame(tag, payload):
    if len(payload) > MAX_BODY:
        raise CodecRefusal('Body limit exceeded')
    return bytes([tag]) + len(payload).to_bytes(8, 'big') + payload


def encode(value, *, allowed_keys=None):
    """Encode strict typed values, preserving raw UTF8 and ordered list bytes."""
    if allowed_keys is not None:
        if type(value) is not dict or set(value) != set(allowed_keys):
            raise CodecRefusal('Exact field schema required')

    def visit(item, depth):
        if depth > MAX_DEPTH:
            raise CodecRefusal('Depth limit exceeded')
        if item is None:
            return _frame(0, b'')
        if type(item) is bool:
            return _frame(1, bytes([int(item)]))
        if type(item) is Unsigned64:
            if not 0 <= item < 2**64:
                raise CodecRefusal('Unsigned integer overflow')
            return _frame(7, int(item).to_bytes(8, 'big'))
        if type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise CodecRefusal('Signed integer overflow')
            return _frame(2, item.to_bytes(8, 'big', signed=True))
        if type(item) is datetime:
            if item.tzinfo is None or item.utcoffset() is None:
                raise CodecRefusal('Aware timestamp required')
            delta = item.astimezone(timezone.utc) - EPOCH
            micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
            return visit(micros, depth)
        if type(item) is str:
            try:
                return _frame(3, item.encode('utf-8', errors='strict'))
            except UnicodeError:
                raise CodecRefusal('Strict UTF8 required') from None
        if type(item) is bytes:
            return _frame(4, item)
        if type(item) in (list, tuple):
            if len(item) > MAX_CHILDREN:
                raise CodecRefusal('Cardinality limit exceeded')
            chunks = [len(item).to_bytes(8, 'big')]
            size = 8
            for child in item:
                data = visit(child, depth + 1)
                size += len(data)
                if size > MAX_BODY:
                    raise CodecRefusal('Body limit exceeded')
                chunks.append(data)
            return _frame(5, b''.join(chunks))
        if type(item) is dict:
            if len(item) > MAX_CHILDREN or any(type(k) is not str for k in item):
                raise CodecRefusal('Strict object keys/cardinality required')
            try:
                keys = sorted(item, key=lambda k: k.encode('utf-8', errors='strict'))
            except UnicodeError:
                raise CodecRefusal('Strict UTF8 keys required') from None
            chunks = [len(item).to_bytes(8, 'big')]
            size = 8
            for key in keys:
                for child in (key, item[key]):
                    data = visit(child, depth + 1)
                    size += len(data)
                    if size > MAX_BODY:
                        raise CodecRefusal('Body limit exceeded')
                    chunks.append(data)
            return _frame(6, b''.join(chunks))
        raise CodecRefusal('Unsupported canonical type')

    result = visit(value, 0)
    if len(result) > MAX_BODY:
        raise CodecRefusal('Body limit exceeded')
    return result


def fingerprint(domain, value, *, allowed_keys=None):
    if domain not in ('SPORTSMODEL:MLB036:CORRECTION_STATE:v1',
                      'SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1',
                      'SPORTSMODEL:MLB036:BUSINESS_STATE:v1',
                      'SPORTSMODEL:MLB036:REQUEST:v1'):
        raise CodecRefusal('Unreviewed fingerprint domain')
    return sha256(encode(domain) + encode(value, allowed_keys=allowed_keys)).hexdigest()
