"""Account directory uses synthetic usernames and read-only local storage."""

import runpy
import sys
import pytest
from app.services.auth import list_accounts


def test_account_list_shows_named_roles_and_status_but_excludes_browser_guests(client):
    auth = client.app.state.auth
    for role in ["admin", "helpdesk", "integration", "applicant"]:
        auth.create_user("directory-" + role, "fixture-list-password", role)
    disabled = auth.create_user("directory-disabled", "fixture-list-password", "admin")
    auth.guest()
    with auth.repository.connect(write=True) as con:
        con.execute("UPDATE principals SET enabled=0 WHERE id=?", (disabled["id"],))
    with auth.repository.connect() as con:
        rows = list_accounts(con, auth.box)
        helpers = list_accounts(con, auth.box, "helpdesk")
    assert {r["login"] for r in rows if r["login"].startswith("directory-")} == {
        "directory-admin",
        "directory-helpdesk",
        "directory-integration",
        "directory-applicant",
        "directory-disabled",
    }
    assert (
        next(r for r in rows if r["login"] == "directory-disabled")["enabled"] is False
    )
    assert all(set(r) == {"login", "role", "enabled"} for r in rows)
    assert "Pemohon" not in [r["login"] for r in rows]
    assert helpers == [
        {"login": "directory-helpdesk", "role": "helpdesk", "enabled": True}
    ]
    with auth.repository.connect() as con:
        with pytest.raises(ValueError):
            list_accounts(con, auth.box, "invalid-role")


def test_cli_lists_accounts_without_changing_password_sessions_or_evidence(
    client, monkeypatch, capsys
):
    auth = client.app.state.auth
    user = auth.create_user("directory-cli", "fixture-list-password", "helpdesk")
    token, _ = auth.login("directory-cli", "fixture-list-password")
    auth.guest()
    with auth.repository.connect() as con:
        original = dict(
            con.execute("SELECT * FROM principals WHERE id=?", (user["id"],)).fetchone()
        )
        counts = {
            t: con.execute("SELECT COUNT(*) AS n FROM " + t).fetchone()["n"]
            for t in ["principals", "auth_sessions", "audit", "evidence"]
        }
    monkeypatch.setattr("app.config.DATA", auth.repository.path.parent)
    monkeypatch.setattr(sys, "argv", ["list_users.py", "--role", "helpdesk"])
    runpy.run_path("scripts/list_users.py", run_name="__main__")
    output = capsys.readouterr().out
    assert "directory-cli" in output and "helpdesk" in output and "Aktif" in output
    assert (
        "fixture-list-password" not in output
        and original["password_hash"] not in output
    )
    assert auth.principal(token)["id"] == user["id"]
    with auth.repository.connect() as con:
        assert (
            dict(
                con.execute(
                    "SELECT * FROM principals WHERE id=?", (user["id"],)
                ).fetchone()
            )
            == original
        )
        assert {
            t: con.execute("SELECT COUNT(*) AS n FROM " + t).fetchone()["n"]
            for t in counts
        } == counts


def test_listing_absent_database_creates_no_files(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "not-created"
    monkeypatch.setattr("app.config.DATA", empty)
    monkeypatch.setattr(sys, "argv", ["list_users.py"])
    runpy.run_path("scripts/list_users.py", run_name="__main__")
    assert "Belum ada database akun" in capsys.readouterr().out
    assert not empty.exists()
