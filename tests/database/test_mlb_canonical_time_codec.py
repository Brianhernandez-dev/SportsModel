"""Pure codec properties; no credentials, database, provider or ambient environment."""
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from hashlib import sha256
import pytest
from sportsmodel.database import mlb_canonical_time_codec as codec
from sportsmodel.database.mlb_canonical_time_codec import CodecRefusal, Unsigned64, encode, fingerprint
from sportsmodel.database.mlb_operator_guard import OperatorRefusal, strict_json


@pytest.mark.parametrize('value,expected',[
    (None,'000000000000000000'),
    (False,'01000000000000000100'),
    (True,'01000000000000000101'),
    (0,'0200000000000000080000000000000000'),
    (-1,'020000000000000008ffffffffffffffff'),
    ('A','03000000000000000141'),
    (b'\x00\xff','04000000000000000200ff'),
    ([], '0500000000000000080000000000000000'),
    ({}, '0600000000000000080000000000000000'),
    (Unsigned64(2**64-1),'070000000000000008ffffffffffffffff'),
])
def test_exact_golden_vectors(value,expected):
    assert encode(value).hex()==expected


def test_object_byte_order_and_timestamps():
    assert encode({'z':1,'é':2,'a':3})==encode({'a':3,'z':1,'é':2})
    assert encode(datetime(1970,1,1,tzinfo=timezone.utc))==encode(0)
    assert encode(datetime(1969,12,31,23,59,59,999999,tzinfo=timezone.utc))==encode(-1)
    assert encode('e\u0301')!=encode('é')
    assert encode([1,2])!=encode([2,1])


@pytest.mark.parametrize('value',[1.0,float('inf'),float('nan'),2**63,-2**63-1,Unsigned64(-1),Unsigned64(2**64),
                                datetime(2026,1,1),{1:'bad'},set(),object()])
def test_unsupported_types_refuse(value):
    with pytest.raises(CodecRefusal):encode(value)


def test_exact_keys_and_depth():
    with pytest.raises(CodecRefusal):encode({'unexpected':1},allowed_keys={'expected'})
    value=0
    for _ in range(33):value=[value]
    with pytest.raises(CodecRefusal):encode(value)
    with pytest.raises(CodecRefusal):encode([0]*100001)
    with pytest.raises(CodecRefusal):encode(b'x'*(16*1024*1024))
    with pytest.raises(CodecRefusal):encode('\ud800')


def test_domain_separation():
    a=fingerprint('SPORTSMODEL:MLB036:CORRECTION_STATE:v1',{'x':1})
    b=fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1',{'x':1})
    assert len(a)==64 and a!=b
    with pytest.raises(CodecRefusal):fingerprint('unreviewed',{})


@pytest.mark.parametrize('value,expected', [
    (-(2**63), '0200000000000000088000000000000000'),
    (2**63-1, '0200000000000000087fffffffffffffff'),
    (Unsigned64(0), '0700000000000000080000000000000000'),
    (Unsigned64(2**63), '0700000000000000088000000000000000'),
    ('é', '030000000000000002c3a9'),
    ('e\u0301', '03000000000000000365cc81'),
    ([None, True], '05000000000000001b000000000000000200000000000000000001000000000000000101'),
    ({'a': None}, '06000000000000001b000000000000000103000000000000000161000000000000000000'),
])
def test_independent_boundary_and_nested_golden_vectors(value, expected):
    """Literal framing vectors are independent of production encoding helpers."""
    assert encode(value).hex() == expected


def test_timestamp_microseconds_are_exact_and_timezone_independent():
    instant = datetime(2026, 7, 12, 17, 40, 0, 123456, tzinfo=timezone.utc)
    offset = instant.astimezone(timezone(timedelta(hours=-7)))
    assert encode(instant) == encode(offset) == encode(1783878000123456)
    assert encode(datetime(1970, 1, 1, 0, 0, 0, 1, tzinfo=timezone.utc)).hex() == (
        '0200000000000000080000000000000001'
    )


class _NonAwareZone(tzinfo):
    def utcoffset(self, _):
        return None


@pytest.mark.parametrize('value', [
    Decimal('1'), Decimal('Infinity'), bytearray(b'x'), memoryview(b'x'),
    datetime(2026, 1, 1, tzinfo=_NonAwareZone()), {'\ud800': 1},
])
def test_no_numeric_or_timestamp_coercion(value):
    with pytest.raises(CodecRefusal):
        encode(value)


@pytest.mark.parametrize('raw', [
    '{"a":1,"a":2}', '{"outer":{"a":1,"a":2}}',
    '{"a":1,"\\u0061":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}',
])
def test_raw_json_parser_refuses_duplicate_or_nonfinite_fields(raw):
    """Duplicate detection must occur before JSON objects lose their source pairs."""
    with pytest.raises(OperatorRefusal):
        strict_json(raw)


@pytest.mark.parametrize('raw', ['{"a":1.0}', '{"a":1e0}', '{"a":9223372036854775808}'])
def test_raw_json_codec_pipeline_refuses_unspecified_numbers(raw):
    with pytest.raises(CodecRefusal):
        encode(strict_json(raw), allowed_keys={'a'})


@pytest.mark.parametrize('value', [{}, {'a': 1, 'extra': 2}, {'wrong': 1}])
def test_schema_rejects_missing_and_unknown_fields(value):
    with pytest.raises(CodecRefusal):
        encode(value, allowed_keys={'a'})


def test_depth_boundary_and_object_cardinality_refuse():
    value = 0
    for _ in range(32):
        value = [value]
    assert encode(value)
    with pytest.raises(CodecRefusal):
        encode([value])
    with pytest.raises(CodecRefusal):
        encode({str(i): None for i in range(100001)})


def test_frame_total_size_not_only_payload_is_bounded():
    assert len(encode(b'x' * (16 * 1024 * 1024 - 9))) == 16 * 1024 * 1024
    with pytest.raises(CodecRefusal):
        encode(b'x' * (16 * 1024 * 1024 - 8))
    with pytest.raises(CodecRefusal):
        encode([b'x' * (8 * 1024 * 1024), b'x' * (8 * 1024 * 1024)])


def test_hash_uses_framed_domain_and_body_not_json_text():
    domain = 'SPORTSMODEL:MLB036:CORRECTION_STATE:v1'
    body = bytes.fromhex('0600000000000000080000000000000000')
    domain_frame = b'\x03' + len(domain.encode('utf8')).to_bytes(8, 'big') + domain.encode('utf8')
    assert fingerprint(domain, {}) == sha256(domain_frame + body).hexdigest()
    assert encode({'a': 1, 'b': 23}) != encode({'a': 12, 'b': 3})
    assert encode(1) != encode(Unsigned64(1))
    assert encode(False) != encode(0)


TIMESTAMP_FIELDS = (
    'old_start', 'new_start', 'game_date', 'gameDate', 'subject_start',
    'recorded_at', 'available_at', 'cutoff_time', 'postmaster_started_at',
    'created_at', 'updated_at', 'snapshot_time',
)
DIGEST_FIELDS = (
    'profile', 'schema_capability_profile', 'ledger034', 'ledger035',
    'projection_digest', 'fence_digest', 'correction_state_fingerprint',
    'identity034_digest', 'identity035_digest', 'receipt_body_sha256',
    'artifact_sha256', 'request_sha256', 'pre_business_sha256',
)


@pytest.mark.parametrize('field', TIMESTAMP_FIELDS)
def test_semantic_timestamp_fields_have_signed_microsecond_golden_frame(field):
    value = codec.semantic_value('1969-12-31T23:59:59.999999Z', field_name=field)
    assert type(value) is datetime
    assert value == datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert encode(value).hex() == '020000000000000008ffffffffffffffff'


@pytest.mark.parametrize('field', DIGEST_FIELDS)
def test_semantic_digest_fields_are_raw32_byte_golden_frame(field):
    value = codec.semantic_value('00' * 32, field_name=field)
    assert type(value) is bytes and len(value) == 32
    assert encode(value).hex() == '040000000000000020' + '00' * 32


@pytest.mark.parametrize('field', ['writer_xid8', 'issuer_xid8'])
@pytest.mark.parametrize('raw', ['18446744073709551615', 18446744073709551615])
def test_semantic_xid8_preserves_unsigned64_golden_frame(field, raw):
    value = codec.semantic_value(raw, field_name=field)
    assert type(value) is Unsigned64
    assert encode(value).hex() == '070000000000000008ffffffffffffffff'


def test_semantic_audit_array_hex_children_have_raw_bytes_golden_frame():
    value = codec.semantic_value(['00', 'ff'], field_name='audits')
    assert value == [b'\x00', b'\xff']
    assert encode(value).hex() == (
        '05000000000000001c0000000000000002'
        '04000000000000000100'
        '040000000000000001ff'
    )


def test_semantic_nested_macro_matches_exact_typed_body_and_preserves_list_order():
    raw = {
        'available_at': '1970-01-01T00:00:00.000001Z',
        'issuer_xid8': '18446744073709551615',
        'profile': '00' * 32,
        'audits': ['00', 'ff'],
        'projection': {'gameDate': '1969-12-31T23:59:59.999999Z', 'game_id': 26},
        'nullable': None,
    }
    typed = {
        'available_at': datetime(1970, 1, 1, 0, 0, 0, 1, tzinfo=timezone.utc),
        'issuer_xid8': Unsigned64(2**64 - 1),
        'profile': b'\x00' * 32,
        'audits': [b'\x00', b'\xff'],
        'projection': {'gameDate': datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc), 'game_id': 26},
        'nullable': None,
    }
    assert encode(codec.semantic_value(raw)) == encode(typed)
    assert encode(codec.semantic_value(dict(reversed(tuple(raw.items()))))) == encode(typed)
    assert fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1', codec.semantic_value(raw)) == (
        fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1', typed)
    )


def test_semantic_receipt_scalar_macro_literal_body_and_sha_golden_vector():
    raw = {'profile': '00' * 32, 'issuer_xid8': '18446744073709551615',
           'available_at': '1970-01-01T00:00:00Z'}
    value = codec.semantic_value(raw)
    # Independently assembled typed frames: three keys in UTF8 byte order.
    assert encode(value).hex() == (
        '06000000000000008c0000000000000003'
        '03000000000000000c617661696c61626c655f6174'
        '0200000000000000080000000000000000'
        '03000000000000000b6973737565725f78696438'
        '070000000000000008ffffffffffffffff'
        '03000000000000000770726f66696c65'
        '040000000000000020' + '00' * 32
    )
    assert fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1', value) == (
        '4b5e5f3315425e1e8112a39a5651e1b51244a312982b75333bfa082e9088327e'
    )


@pytest.mark.parametrize('field', ['officialDate', 'official_date'])
def test_semantic_official_date_is_strict_utf8_not_timestamp(field):
    value = codec.semantic_value('2026-07-12', field_name=field)
    assert type(value) is str
    assert encode(value).hex() == '03000000000000000a323032362d30372d3132'


@pytest.mark.parametrize('field', ['officialDate', 'official_date'])
@pytest.mark.parametrize('raw', ['2026-2-3', '2026-02-30', '0000-01-01',
                               '2026-07-12T00:00:00Z', '2026-07-12 ', 20260712, False, {}])
def test_semantic_official_date_invalid_calendar_or_type_refuses(field, raw):
    with pytest.raises(CodecRefusal):
        codec.semantic_value(raw, field_name=field)


def test_semantic_macros_duplicate_fields_refuse_at_raw_boundary():
    with pytest.raises(OperatorRefusal):
        codec.semantic_value(strict_json('{"available_at":null,"available_at":"1970-01-01T00:00:00Z"}'))


@pytest.mark.parametrize('field', TIMESTAMP_FIELDS + DIGEST_FIELDS + ('writer_xid8', 'issuer_xid8', 'audit_bytes'))
def test_semantic_nullable_fields_remain_explicit_null(field):
    assert encode(codec.semantic_value(None, field_name=field)).hex() == '000000000000000000'


@pytest.mark.parametrize('raw', [
    '1970-01-01T00:00:00', 'not-a-time', 'infinity', '-infinity',
    '2026-02-30T00:00:00Z', '2026-01-01T25:00:00Z',
    '2026-01-01T24:00:00Z',
    '1970-01-01T00:00:00.1234567Z', '1970-01-01T00:00:00.1234567+00:00',
    '1970-01-01T00:00:00+99:00',
    0, False, [], {}, datetime(1970, 1, 1, tzinfo=timezone.utc),
])
def test_semantic_timestamp_malformed_or_untyped_values_refuse(raw):
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value(raw, field_name='available_at'))


@pytest.mark.parametrize('raw', ['', '00' * 31, '00' * 33, 'AB' * 32, 'gg' * 32, 0, False, [], {}])
def test_semantic_digest_malformed_length_case_or_type_refuses(raw):
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value(raw, field_name='evidence_sha256'))


@pytest.mark.parametrize('raw', [-1, 2**64, '-1', '18446744073709551616', '+1',
                               '1.0', '1e0', True, 1.0, [], {}])
def test_semantic_xid8_unsupported_numeric_types_or_overflow_refuse(raw):
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value(raw, field_name='issuer_xid8'))


@pytest.mark.parametrize('raw', ['', '0', 'ff0', 'FF', 'gg', 1, False, {}, []])
def test_semantic_audit_bytes_malformed_type_or_hex_refuses(raw):
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value(raw, field_name='audit_bytes'))


@pytest.mark.parametrize('raw', [{}, {'available_at': None, 'extra': None}])
def test_semantic_macros_still_require_explicit_exact_object_schema(raw):
    with pytest.raises(CodecRefusal):
        fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1', codec.semantic_value(raw),
                    allowed_keys={'available_at'})


def test_semantic_macro_bounds_and_no_unicode_normalization():
    value = 0
    for _ in range(33):
        value = [value]
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value(value))
    with pytest.raises(CodecRefusal):
        encode(codec.semantic_value([0] * 100001))
    assert encode(codec.semantic_value({'label': 'e\u0301'})) != encode(codec.semantic_value({'label': 'é'}))
    assert encode(codec.semantic_value({'profile_label': '00' * 32})) == encode({'profile_label': '00' * 32})
