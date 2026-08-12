"""Execute the reconciliation migration against an isolated PostgreSQL 17 cluster."""

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests/sql/resume_reconciliation_base.sql"
MIGRATIONS = (
    ROOT / "supabase/migrations/20260812170000_resume_reconciliation_staging.sql",
    ROOT / "supabase/migrations/20260812180000_restrict_resume_reconciliation_rpc.sql",
)
ASSERTIONS = ROOT / "tests/sql/resume_reconciliation_assertions.sql"
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
def test_resume_reconciliation_migration_and_rpc(tmp_path):
    data = tmp_path / "pgdata"
    port = _free_port()
    env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGDATABASE": "postgres"}
    _run([str(PG_BIN / "initdb"), "-D", str(data), "--auth=trust", "--no-locale"])
    try:
        _run(
            [
                str(PG_BIN / "pg_ctl"), "-D", str(data),
                "-l", str(tmp_path / "postgres.log"),
                "-o", f"-p {port} -k /tmp", "-w", "-t", "15", "start",
            ]
        )
        for sql in (BASE, *MIGRATIONS):
            _run([str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", "-f", str(sql)], env=env)
        _seed(env)
        _run([str(PG_BIN / "psql"), "-f", str(ASSERTIONS)], env=env)
    finally:
        if data.exists():
            subprocess.run(
                [str(PG_BIN / "pg_ctl"), "-D", str(data), "-m", "immediate", "stop"],
                check=False,
                capture_output=True,
            )
            shutil.rmtree(data, ignore_errors=True)


def _seed(env):
    sql = r"""
insert into students(id,auth_user_id,name,major_current,major_intended,expected_graduation,updated_at) values
('10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','A','Computer Science','N/A','Fall 2030','2026-01-01Z'),
('10000000-0000-0000-0000-000000000002','20000000-0000-0000-0000-000000000002','B','History',null,null,'2026-01-01Z');
insert into career_profiles(id,student_id,target_roles,interests,ai_anxiety_level,skills_technical,skills_soft,source,confirmed_at,updated_at) values
('70000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001',array['Engineer'],array['Robotics'],'low',array['Python','React','Docker'],array['Communication'],'resume_parse','2026-01-01Z','2026-01-01Z'),
('70000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002',array[]::text[],array[]::text[],null,array[]::text[],array[]::text[],'manual','2026-01-01Z','2026-01-01Z');
insert into work_experience(id,career_profile_id,student_id,employer,role,duration,source,confirmed_at,updated_at) values
('40000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','Praxigen','Intern','Jun 2026 - Present','resume_parse','2026-01-01Z','2026-01-01Z');
insert into projects(id,career_profile_id,student_id,name,source,confirmed_at,updated_at) values
('50000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','GradusIQ','resume_parse','2026-01-01Z','2026-01-01Z');
insert into certifications(id,career_profile_id,student_id,name,issuer,status,source,confirmed_at,updated_at) values
('60000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','Existing Cert','Issuer','completed','resume_parse','2026-01-01Z','2026-01-01Z');
insert into resume_reconciliations(id,student_id,status,academic_proposal,skills_proposal,base_student_updated_at,base_career_profile_updated_at) values
('30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','pending','{"major_current":{"value":"Computer Engineering","decision":"accept"},"expected_graduation":{"value":"Spring 2029","decision":"accept"}}','{"technical":[{"value":"python","decision":"accept"},{"value":"PyTorch","decision":"accept"}]}','2026-01-01Z','2026-01-01Z'),
('30000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','pending','{}','{}','2026-01-01Z','2026-01-01Z');
insert into resume_reconciliation_items(id,reconciliation_id,student_id,domain,classification,canonical_row_id,canonical_row_updated_at,proposed_value,decision) values
(gen_random_uuid(),'30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','work_experience','update','40000000-0000-0000-0000-000000000001','2026-01-01Z','{"duration":"Jun 2026 - Aug 2026"}','accept'),
(gen_random_uuid(),'30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','project','add',null,null,'{"name":"SAFE-AGENT","description":"Safety research","tools":["Python"]}','accept'),
(gen_random_uuid(),'30000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','certification','add',null,null,'{"name":"NVIDIA Associate","issuer":"NVIDIA","status":"completed"}','accept');
"""
    _run([str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", "-c", sql], env=env)
