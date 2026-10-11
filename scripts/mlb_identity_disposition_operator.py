"""Explicit bounded MLB identity operator; read the reviewed runbook first."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sportsmodel.operations.mlb_identity_disposition_cli import main

if __name__=='__main__':
    raise SystemExit(main())
