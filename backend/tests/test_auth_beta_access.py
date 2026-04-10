import pytest
from fastapi import HTTPException

from auth import ensure_beta_access, is_valid_beta_invite_code, parse_email_allowlist


def test_parse_email_allowlist_normalizes_case_and_spacing():
    parsed = parse_email_allowlist(
        " invited@example.com,TEAM@example.com ",
        "ops@example.com",
    )

    assert parsed == [
        "invited@example.com",
        "team@example.com",
        "ops@example.com",
    ]


def test_ensure_beta_access_allows_open_mode(monkeypatch):
    monkeypatch.delenv("BETA_INVITE_CODE", raising=False)
    monkeypatch.delenv("OPS_ADMIN_EMAILS", raising=False)
    monkeypatch.setenv("TESTING", "0")

    ensure_beta_access("user-1", "user@example.com")


def test_ensure_beta_access_denies_user_without_granted_flag(monkeypatch):
    monkeypatch.setenv("BETA_INVITE_CODE", "Daily Drop")
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("auth.is_admin_email", lambda _email: False)
    monkeypatch.setattr("auth._settings_beta_access_granted", lambda _user_id: False)

    with pytest.raises(HTTPException) as exc_info:
        ensure_beta_access("user-1", "user@example.com")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Enter the beta invite code to continue."


def test_ensure_beta_access_allows_admin_allowlist_match(monkeypatch):
    monkeypatch.setenv("BETA_INVITE_CODE", "Daily Drop")
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setattr("auth.is_admin_email", lambda _email: True)

    ensure_beta_access("user-1", "Ops@Example.Com")


def test_is_valid_beta_invite_code_accepts_friendly_variants(monkeypatch):
    monkeypatch.setenv("BETA_INVITE_CODE", "Daily Drop")

    assert is_valid_beta_invite_code("dailydrop") is True
    assert is_valid_beta_invite_code("daily-drop") is True
    assert is_valid_beta_invite_code("DAILY DROP") is True
    assert is_valid_beta_invite_code("othercode") is False
