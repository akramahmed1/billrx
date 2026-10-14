"""Row-level security and audit tests against a real Postgres.

Set BILLRX_TEST_DATABASE_URL to a superuser connection URL (any database; a
fresh test database is created next to it). Skipped when unset. Uses psql so it
needs no Python database driver.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

BASE_URL = os.getenv("BILLRX_TEST_DATABASE_URL", "")
MIGRATION = Path(__file__).resolve().parent.parent / "db" / "migrations" / "0001_tenancy.sql"

if not BASE_URL or not shutil.which("psql"):
    pytest.skip("BILLRX_TEST_DATABASE_URL not set or psql missing", allow_module_level=True)

# Fixed ids keep the assertions readable.
ORG1, ORG2 = "00000000-0000-0000-0000-0000000000a1", "00000000-0000-0000-0000-0000000000a2"
OWNER1, ADVOCATE1, VIEWER1, OWNER2 = (f"00000000-0000-0000-0000-00000000000{i}" for i in (1, 2, 3, 4))
CLIENT1, CLIENT2 = "00000000-0000-0000-0000-0000000000c1", "00000000-0000-0000-0000-0000000000c2"
CASE1 = "00000000-0000-0000-0000-0000000000d1"
SHA = "a" * 64

_DB_URL: str | None = None


def _url_for(db: str) -> str:
    head, _, _ = BASE_URL.rpartition("/")
    return f"{head}/{db}"


def _psql(url: str, sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(["psql", url, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"],
                          input=sql, capture_output=True, text=True)


def db() -> str:
    """Create a fresh database once per test run, migrate and seed it."""
    global _DB_URL
    if _DB_URL:
        return _DB_URL
    name = f"billrx_test_{uuid.uuid4().hex[:10]}"
    r = _psql(BASE_URL, f"CREATE DATABASE {name};")
    assert r.returncode == 0, r.stderr
    url = _url_for(name)
    r = _psql(url, MIGRATION.read_text())
    assert r.returncode == 0, r.stderr
    seed = f"""
    SET search_path = billrx;
    INSERT INTO users (id, auth_subject, email) VALUES
      ('{OWNER1}', 'auth|o1', 'owner1@example.test'),
      ('{ADVOCATE1}', 'auth|a1', 'advocate1@example.test'),
      ('{VIEWER1}', 'auth|v1', 'viewer1@example.test'),
      ('{OWNER2}', 'auth|o2', 'owner2@example.test');
    INSERT INTO organizations (id, name, kind) VALUES
      ('{ORG1}', 'Acme Advocates', 'advocate_practice'),
      ('{ORG2}', 'Personal', 'personal');
    INSERT INTO memberships (org_id, user_id, role) VALUES
      ('{ORG1}', '{OWNER1}', 'owner'), ('{ORG1}', '{ADVOCATE1}', 'advocate'),
      ('{ORG1}', '{VIEWER1}', 'viewer'), ('{ORG2}', '{OWNER2}', 'owner');
    INSERT INTO clients (id, org_id, display_name) VALUES
      ('{CLIENT1}', '{ORG1}', 'Client One'), ('{CLIENT2}', '{ORG2}', 'Me');
    INSERT INTO cases (id, org_id, client_id, title) VALUES
      ('{CASE1}', '{ORG1}', '{CLIENT1}', 'ER visit August');
    """
    r = _psql(url, seed)
    assert r.returncode == 0, r.stderr
    _DB_URL = url
    return url


def as_user(user_id: str | None, sql: str) -> subprocess.CompletedProcess:
    """Run SQL exactly as the application would: app role + per-transaction user."""
    ctx = f"SET LOCAL billrx.user_id = '{user_id}';" if user_id else ""
    return _psql(db(), f"SET ROLE billrx_app; BEGIN; {ctx} SET LOCAL search_path = billrx; "
                       f"{sql}; COMMIT;")


def value(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""


def denied(r: subprocess.CompletedProcess) -> bool:
    return r.returncode != 0 and ("row-level security" in r.stderr
                                  or "permission denied" in r.stderr
                                  or "append-only" in r.stderr)


def test_users_only_see_their_own_tenant():
    assert value(as_user(ADVOCATE1, "SELECT string_agg(display_name, ',') FROM clients")) == "Client One"
    assert value(as_user(OWNER2, "SELECT string_agg(display_name, ',') FROM clients")) == "Me"
    assert value(as_user(OWNER2, "SELECT count(*) FROM cases")) == "0"


def test_no_user_in_session_sees_nothing():
    for table in ("organizations", "clients", "cases", "memberships"):
        assert value(as_user(None, f"SELECT count(*) FROM {table}")) == "0", table


def test_cannot_write_into_another_tenant():
    r = as_user(ADVOCATE1, f"INSERT INTO clients (org_id, display_name) VALUES ('{ORG2}', 'x')")
    assert denied(r), r.stderr


def test_viewers_are_read_only():
    r = as_user(VIEWER1, f"INSERT INTO cases (org_id, client_id, title) "
                         f"VALUES ('{ORG1}', '{CLIENT1}', 'nope')")
    assert denied(r), r.stderr
    assert int(value(as_user(VIEWER1, "SELECT count(*) FROM cases"))) >= 1


def test_cross_tenant_references_are_impossible_even_without_rls():
    # Superuser bypasses RLS, but the composite foreign key still refuses.
    r = _psql(db(), f"INSERT INTO billrx.cases (org_id, client_id, title) "
                    f"VALUES ('{ORG1}', '{CLIENT2}', 'mixed')")
    assert r.returncode != 0 and "foreign key" in r.stderr


def test_changes_are_audited_without_phi_values():
    case_id = str(uuid.uuid4())
    r = as_user(ADVOCATE1, f"""
        INSERT INTO cases (id, org_id, client_id, title)
          VALUES ('{case_id}', '{ORG1}', '{CLIENT1}', 'Secret diagnosis detail');
        UPDATE cases SET status = 'in_review' WHERE id = '{case_id}'""")
    assert r.returncode == 0, r.stderr
    rows = value(as_user(OWNER1, f"""
        SELECT string_agg(action || ':' || array_to_string(changed_fields, '|'), ',' ORDER BY id)
        FROM audit_log WHERE entity_id = '{case_id}'"""))
    insert, update = rows.split(",")
    assert insert == "insert:" and "status" in update.split(":")[1].split("|")
    actor = value(as_user(OWNER1, f"SELECT DISTINCT actor_user_id FROM audit_log "
                                  f"WHERE entity_id = '{case_id}'"))
    assert actor == ADVOCATE1
    dump = value(as_user(OWNER1, "SELECT string_agg(audit_log::text, ' ') FROM audit_log"))
    assert "Secret diagnosis" not in dump


def test_audit_log_is_readable_by_managers_only_and_append_only():
    assert int(value(as_user(OWNER1, "SELECT count(*) FROM audit_log"))) > 0
    assert value(as_user(ADVOCATE1, "SELECT count(*) FROM audit_log")) == "0"
    assert denied(as_user(OWNER1, "DELETE FROM audit_log"))
    superuser = _psql(db(), "UPDATE billrx.audit_log SET action = 'delete'")
    assert superuser.returncode != 0 and "append-only" in superuser.stderr


def test_approvals_must_be_signed_by_the_current_user():
    forged = as_user(ADVOCATE1, f"INSERT INTO approvals (org_id, case_id, artifact, content_sha256, "
                                f"approved_by) VALUES ('{ORG1}', '{CASE1}', 'appeal_letter', "
                                f"'{SHA}', '{OWNER1}')")
    assert denied(forged), forged.stderr
    own = as_user(ADVOCATE1, f"INSERT INTO approvals (org_id, case_id, artifact, content_sha256, "
                             f"approved_by) VALUES ('{ORG1}', '{CASE1}', 'appeal_letter', "
                             f"'{SHA}', '{ADVOCATE1}')")
    assert own.returncode == 0, own.stderr
    assert denied(as_user(ADVOCATE1, "UPDATE approvals SET content_sha256 = content_sha256"))


def test_signup_creates_an_owned_org_and_the_last_owner_cannot_leave():
    new_user = str(uuid.uuid4())
    assert _psql(db(), f"INSERT INTO billrx.users (id, auth_subject, email) VALUES "
                       f"('{new_user}', 'auth|new', 'new@example.test')").returncode == 0
    org = value(as_user(new_user, "SELECT create_organization('My bills', 'personal')"))
    assert value(as_user(new_user, f"SELECT role FROM memberships WHERE org_id = '{org}'")) == "owner"
    leave = as_user(new_user, f"DELETE FROM memberships WHERE org_id = '{org}'")
    assert leave.returncode != 0 and "at least one owner" in leave.stderr


def test_managers_add_members_but_advocates_cannot():
    hire = str(uuid.uuid4())
    assert _psql(db(), f"INSERT INTO billrx.users (id, auth_subject, email) VALUES "
                       f"('{hire}', 'auth|{hire}', '{hire}@example.test')").returncode == 0
    by_advocate = as_user(ADVOCATE1, f"INSERT INTO memberships (org_id, user_id, role) "
                                     f"VALUES ('{ORG1}', '{hire}', 'viewer')")
    assert denied(by_advocate), by_advocate.stderr
    by_owner = as_user(OWNER1, f"INSERT INTO memberships (org_id, user_id, role) "
                               f"VALUES ('{ORG1}', '{hire}', 'viewer')")
    assert by_owner.returncode == 0, by_owner.stderr
