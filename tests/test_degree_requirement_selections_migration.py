"""Execute the Degree Schedule selection foundation in isolated PostgreSQL."""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests/sql/degree_requirement_selections_base.sql"
MIGRATION = ROOT / "supabase/migrations/20260824120000_degree_requirement_selections.sql"
ASSERTIONS = ROOT / "tests/sql/degree_requirement_selections_assertions.sql"
PG_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")


def _run(args, **kwargs):
    result = subprocess.run(args, text=True, capture_output=True, **kwargs)
    if result.returncode:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(str, args))}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.skipif(not (PG_BIN / "initdb").exists(), reason="PostgreSQL 17 is unavailable")
def test_degree_requirement_selections_schema_rls_and_constraints(tmp_path):
    data = tmp_path / "pgdata"
    port = _free_port()
    env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGDATABASE": "postgres"}
    _run([str(PG_BIN / "initdb"), "-D", str(data), "--auth=trust", "--no-locale"])
    try:
        _run([
            str(PG_BIN / "pg_ctl"), "-D", str(data), "-l", str(tmp_path / "postgres.log"),
            "-o", f"-p {port} -k /tmp", "-w", "-t", "15", "start",
        ])
        for sql in (BASE, MIGRATION, ASSERTIONS):
            _run([str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", "-f", str(sql)], env=env)
    finally:
        if data.exists():
            subprocess.run(
                [str(PG_BIN / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"],
                check=False, capture_output=True,
            )
            shutil.rmtree(data, ignore_errors=True)
