"""Explicit secret-safe identity operator surface; no environment discovery."""
import argparse
import getpass
from pathlib import Path
import stat
import warnings

from sportsmodel.database.mlb_operator_guard import OperatorTarget, OperatorRefusal, strict_json, canonical_json
from sportsmodel.operations.mlb_identity_disposition import (
    preview_disposition,execute_disposition,inspect_receipt,
)


def _local_path(path):
    if str(path).startswith('\\\\') or path.name.lower()=='.env':
        raise OperatorRefusal('Local non-secret evidence path required')
    path=path.absolute()
    for ancestor in (path,*path.parents):
        if ancestor.exists():
            value=ancestor.lstat()
            if stat.S_ISLNK(value.st_mode) or getattr(value,'st_file_attributes',0)&0x400:
                raise OperatorRefusal('Linked evidence paths are not admitted')
    return path


def _read(path,limit):
    path=_local_path(path)
    if not path.is_file() or path.stat().st_size>limit:
        raise OperatorRefusal('Bounded evidence file required')
    with path.open('rb') as stream:
        value=stream.read(limit+1)
    if len(value)>limit:
        raise OperatorRefusal('Evidence grew beyond bound')
    return value


def main(argv=None, *, connector=None, password_reader=None):
    parser=argparse.ArgumentParser(description='Reviewed bounded MLB identity disposition; no provider calls')
    parser.add_argument('action',choices=['preview','activate','revoke-reviewed','receipt'])
    parser.add_argument('--target',required=True,type=Path)
    parser.add_argument('--db-user',required=True)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--request',type=Path)
    parser.add_argument('--evidence',type=Path)
    parser.add_argument('--preview',type=Path)
    parser.add_argument('--approved-preview-sha256')
    parser.add_argument('--receipt-sha256')
    parser.add_argument('--acknowledge-db-read',action='store_true')
    parser.add_argument('--acknowledge-writes',action='store_true')
    parser.add_argument('--acknowledge-survivor-anchor',action='store_true')
    parser.add_argument('--acknowledge-reviewed-reversal',action='store_true')
    args=parser.parse_args(argv)
    password=None
    try:
        if not args.acknowledge_db_read:
            raise OperatorRefusal('Explicit read authority required')
        target=OperatorTarget.from_dict(strict_json(_read(args.target,16_000)))
        args.output=_local_path(args.output)
        if args.output.exists() or args.output.suffix!='.json' or not args.output.parent.is_dir():
            raise OperatorRefusal('Fresh local JSON output required')
        output=args.output.resolve()
        root=Path(__file__).resolve().parents[3]
        if output.is_relative_to(root) or output.is_relative_to(Path('D:/SportsModel')):
            raise OperatorRefusal('Operator evidence must remain outside development/production repositories')
        request_bytes=evidence_bytes=None
        if args.action!='receipt':
            if args.request is None or args.evidence is None:
                raise OperatorRefusal('Explicit executable request/evidence required')
            request_bytes=_read(args.request,128_000);evidence_bytes=_read(args.evidence,10_000_000)
            from sportsmodel.operations.mlb_identity_disposition import validate_request
            request,_=validate_request(request_bytes,evidence_bytes)
            expected='REVOKE' if args.action=='revoke-reviewed' else 'ACTIVATE'
            if request['action']!=expected:
                raise OperatorRefusal('Command and request action differ')
        if args.action in ('activate','revoke-reviewed') and (not args.acknowledge_writes or args.preview is None or not args.approved_preview_sha256):
            raise OperatorRefusal('Exact preview and separate write authority required')
        if args.action=='revoke-reviewed' and not args.acknowledge_reviewed_reversal:
            raise OperatorRefusal('Explicit reviewed reversal acknowledgement required')
        preview_bytes=_read(args.preview,20_000_000) if args.preview else None
        reader=password_reader or getpass.getpass
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            password=reader('Database password (non-persistent): ')
        if not password:
            raise OperatorRefusal('Non-echoing explicit credential required')
        if connector is None:
            import psycopg2
            connector=psycopg2.connect
        def factory():
            return connector(host=target.host,port=target.port,dbname=target.database,
                             user=args.db_user,password=password,connect_timeout=5,
                             options='-c lock_timeout=5000ms -c statement_timeout=30000ms')
        if args.action=='preview':
            result=preview_disposition(request_bytes=request_bytes,evidence_bytes=evidence_bytes,target=target,connection_factory=factory)
        elif args.action=='receipt':
            result=inspect_receipt(approved_manifest_sha256=args.receipt_sha256,target=target,connection_factory=factory)
        else:
            result=execute_disposition(request_bytes=request_bytes,evidence_bytes=evidence_bytes,
                preview=strict_json(preview_bytes),approved_preview_sha256=args.approved_preview_sha256,
                target=target,connection_factory=factory,acknowledge_writes=args.acknowledge_writes,
                acknowledge_survivor_anchor=args.acknowledge_survivor_anchor)
        with output.open('x',encoding='utf-8',newline='\n') as file:
            file.write(canonical_json(result)+'\n')
        return 0
    except Exception:
        print('Identity operation refused or outcome uncertain; inspect retained evidence before any retry. No automatic retry.')
        return 1
    finally:
        password=None


if __name__=='__main__':
    raise SystemExit(main())
