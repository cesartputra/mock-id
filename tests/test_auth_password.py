"""Password rotation tests use disposable local accounts, never user passwords."""

import getpass
import runpy
import sys
import pytest
from fastapi import HTTPException
from app.services.auth import AuthService


def test_reset_preserves_account_data_and_revokes_only_its_sessions(client):
    auth = client.app.state.auth
    user = auth.create_user("reset-user", "fixture-old-password", "helpdesk")
    first, _ = auth.login("reset-user", "fixture-old-password")
    second, _ = auth.login("reset-user", "fixture-old-password")
    other = auth.create_user("other-reset", "fixture-other-password", "admin")
    other_token, _ = auth.login("other-reset", "fixture-other-password")
    guest_token, guest = auth.guest()
    with auth.repository.connect() as con:
        before = dict(
            con.execute("SELECT * FROM principals WHERE id=?", (user["id"],)).fetchone()
        )
    changed = auth.set_password(" RESET-USER ", "fixture-new-password")
    assert changed == user
    for token in [first, second]:
        with pytest.raises(HTTPException) as error:
            auth.principal(token)
        assert error.value.status_code == 401
    assert auth.principal(other_token)["id"] == other["id"]
    assert auth.principal(guest_token)["id"] == guest["id"]
    with pytest.raises(HTTPException):
        auth.login("reset-user", "fixture-old-password")
    new_token, current = auth.login("reset-user", "fixture-new-password")
    assert current["id"] == user["id"] and current["role"] == "helpdesk"
    assert auth.principal(new_token)["id"] == user["id"]
    with auth.repository.connect() as con:
        after = dict(
            con.execute("SELECT * FROM principals WHERE id=?", (user["id"],)).fetchone()
        )
        audit = con.execute(
            "SELECT detail FROM audit WHERE ref=? AND type='Password akun diperbarui'",
            (user["id"],),
        ).fetchone()
    for field in ["id", "login", "display_login", "role", "enabled", "auth_kind"]:
        assert before[field] == after[field]
    assert before["password_hash"] != after["password_hash"]
    assert "fixture-new-password" not in after["password_hash"]
    assert audit and "password" not in audit["detail"].lower()


@pytest.mark.parametrize(
    "login,password,code",
    [
        ("valid-reset", "short", 422),
        ("valid-reset", "x" * 201, 422),
        ("missing-user", "fixture-new-password", 404),
    ],
)
def test_invalid_reset_keeps_old_password_and_sessions(client, login, password, code):
    auth = client.app.state.auth
    user = auth.create_user("valid-reset", "fixture-old-password", "admin")
    token, _ = auth.login("valid-reset", "fixture-old-password")
    with pytest.raises(HTTPException) as error:
        auth.set_password(login, password)
    assert error.value.status_code == code
    assert auth.principal(token)["id"] == user["id"]
    assert auth.login("valid-reset", "fixture-old-password")[1]["id"] == user["id"]


@pytest.mark.parametrize("kind", ["disabled", "browser"])
def test_reset_does_not_enable_disabled_or_browser_accounts(client, kind):
    auth = client.app.state.auth
    user = auth.create_user("protected-reset", "fixture-old-password", "applicant")
    with auth.repository.connect(write=True) as con:
        if kind == "disabled":
            con.execute("UPDATE principals SET enabled=0 WHERE id=?", (user["id"],))
        else:
            con.execute(
                "UPDATE principals SET auth_kind='browser' WHERE id=?", (user["id"],)
            )
        before = con.execute(
            "SELECT password_hash FROM principals WHERE id=?", (user["id"],)
        ).fetchone()["password_hash"]
    with pytest.raises(HTTPException) as error:
        auth.set_password("protected-reset", "fixture-new-password")
    assert error.value.status_code == 403
    with auth.repository.connect() as con:
        assert (
            con.execute(
                "SELECT password_hash FROM principals WHERE id=?", (user["id"],)
            ).fetchone()["password_hash"]
            == before
        )


def test_login_racing_with_reset_cannot_issue_a_stale_token(client, monkeypatch):
    import app.services.auth as module

    auth = client.app.state.auth
    user = auth.create_user("race-reset", "fixture-old-password", "admin")
    previous, _ = auth.login("race-reset", "fixture-old-password")
    original = module.hashlib.scrypt
    armed = [True]

    def racing_hash(*args, **kwargs):
        computed = original(*args, **kwargs)
        if armed[0]:
            armed[0] = False
            auth.set_password("race-reset", "fixture-new-password")
        return computed

    monkeypatch.setattr(module.hashlib, "scrypt", racing_hash)
    with pytest.raises(HTTPException) as error:
        auth.login("race-reset", "fixture-old-password")
    assert error.value.status_code == 401
    with pytest.raises(HTTPException):
        auth.principal(previous)
    with auth.repository.connect() as con:
        assert (
            con.execute(
                "SELECT COUNT(*) AS n FROM auth_sessions WHERE principal_id=?",
                (user["id"],),
            ).fetchone()["n"]
            == 0
        )
    assert auth.login("race-reset", "fixture-new-password")[1]["id"] == user["id"]


def test_cli_reset_uses_hidden_prompts_and_does_not_print_password(
    client, monkeypatch, capsys
):
    auth = client.app.state.auth
    user = auth.create_user("cli-reset", "fixture-old-password", "admin")
    token, _ = auth.login("cli-reset", "fixture-old-password")
    monkeypatch.setattr("app.config.DATA", auth.repository.path.parent)
    monkeypatch.setattr(sys, "argv", ["change_password.py", "--login", "cli-reset"])
    answers = iter(["fixture-new-password", "fixture-new-password"])
    monkeypatch.setattr(getpass, "getpass", lambda _: next(answers))
    runpy.run_path("scripts/change_password.py", run_name="__main__")
    output = capsys.readouterr()
    assert "Password diperbarui untuk: cli-reset" in output.out
    assert "fixture-new-password" not in output.out + output.err
    assert auth.login("cli-reset", "fixture-new-password")[1]["id"] == user["id"]
    with pytest.raises(HTTPException):
        auth.principal(token)


def test_cli_mismatch_changes_nothing(client, monkeypatch):
    auth = client.app.state.auth
    user = auth.create_user("mismatch-reset", "fixture-old-password", "admin")
    token, _ = auth.login("mismatch-reset", "fixture-old-password")
    monkeypatch.setattr("app.config.DATA", auth.repository.path.parent)
    monkeypatch.setattr(
        sys, "argv", ["change_password.py", "--login", "mismatch-reset"]
    )
    answers = iter(["fixture-new-password", "fixture-other-password"])
    monkeypatch.setattr(getpass, "getpass", lambda _: next(answers))
    with pytest.raises(SystemExit, match="Password tidak sama"):
        runpy.run_path("scripts/change_password.py", run_name="__main__")
    assert auth.principal(token)["id"] == user["id"]


def test_cli_refuses_visible_getpass_fallback(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["change_password.py", "--login", "fixture-reset"])

    def unsafe_prompt(_):
        raise getpass.GetPassWarning("fixture no tty")

    monkeypatch.setattr(getpass, "getpass", unsafe_prompt)
    with pytest.raises(SystemExit, match="terminal interaktif"):
        runpy.run_path("scripts/change_password.py", run_name="__main__")


def test_reset_clears_only_target_account_login_limit(client):
    auth = client.app.state.auth
    auth.create_user("locked-reset", "fixture-old-password", "admin")
    buckets = [
        "login:" + auth.box.subject("login:" + name)
        for name in ["locked-reset", "other-reset"]
    ]
    for bucket in buckets:
        for _ in range(10):
            auth.limit(bucket, 10, 300)
    with pytest.raises(HTTPException) as error:
        auth.login("locked-reset", "fixture-old-password")
    assert error.value.status_code == 429
    auth.set_password("locked-reset", "fixture-new-password")
    assert (
        auth.login("locked-reset", "fixture-new-password")[1]["login"] == "locked-reset"
    )
    with pytest.raises(HTTPException) as error:
        auth.limit(buckets[1], 10, 300)
    assert error.value.status_code == 429
