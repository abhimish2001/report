"""
test_auth_guards.py
Regression tests for the authentication boundary.

Every state-changing or data-exposing route must reject anonymous callers with
a redirect to /login. These were previously wide open - an unauthenticated
visitor could POST /reset-db to wipe the whole reports table, enumerate
sequential report ids through /export/*, or burn Gemini quota via
/api/regenerate-ai. Each of those is pinned here so removing a
`get_current_user` guard fails the suite instead of silently reopening the hole.
"""

from __future__ import annotations

import pytest


def test_health_endpoint_stays_public(anon_client):
    """Monitoring probes must not require a session."""
    assert anon_client.get("/health").status_code == 200


def test_login_and_register_pages_are_public(anon_client):
    assert anon_client.get("/login").status_code == 200
    assert anon_client.get("/register").status_code == 200


@pytest.mark.parametrize(
    "method,url,kwargs",
    [
        ("get", "/load-demo", {}),
        ("post", "/reset-db", {}),
        (
            "post",
            "/api/regenerate-ai",
            {"data": {"report_id": "1", "gemini_api_key": "unused"}},
        ),
        ("get", "/export/excel/1", {}),
        ("get", "/export/pdf/1", {}),
    ],
)
def test_mutating_and_export_routes_reject_anonymous_users(anon_client, method, url, kwargs):
    resp = getattr(anon_client, method)(url, follow_redirects=False, **kwargs)
    assert resp.status_code == 303, f"{method.upper()} {url} was not blocked"
    assert resp.headers["location"] == "/login"


def test_anonymous_reset_db_cannot_wipe_reports(client, anon_client, demo_report_id):
    """The guard must fire before clear_all_data(), not after."""
    assert client.get("/health").json()["total_reports"] == 1

    resp = anon_client.post("/reset-db", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    assert client.get("/health").json()["total_reports"] == 1


def test_authenticated_user_can_still_reset_db(client, demo_report_id):
    assert client.get("/health").json()["total_reports"] == 1
    resp = client.post("/reset-db", follow_redirects=False)
    assert resp.status_code == 303
    assert client.get("/health").json()["total_reports"] == 0


def test_unknown_credentials_are_rejected(anon_client):
    resp = anon_client.post(
        "/login",
        data={"email": "ghost@example.com", "password": "not-a-real-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith("/login")
    assert "error" in location
    assert not anon_client.cookies.get("session_id")


def test_register_then_login_flow(anon_client, delete_user):
    email = "newbie.tl@example.com"
    delete_user(email)

    resp = anon_client.post(
        "/register",
        data={
            "name": "New TL",
            "email": email,
            "password": "brand-new-pass-9",
            "role": "TL",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    resp = anon_client.post(
        "/login",
        data={"email": email, "password": "brand-new-pass-9"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/dashboard"
    assert anon_client.cookies.get("session_id")

    assert anon_client.get("/dashboard").status_code == 200


def test_register_rejects_unknown_role(anon_client, delete_user):
    email = "qa.robot@example.com"
    delete_user(email)

    resp = anon_client.post(
        "/register",
        data={"name": "Robot", "email": email, "password": "robot-pass-123", "role": "ADMIN"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]

    resp = anon_client.post(
        "/login",
        data={"email": email, "password": "robot-pass-123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error" in resp.headers["location"]


def test_member_role_cannot_open_team_page(db_state, delete_user):
    from fastapi.testclient import TestClient
    from modules import auth
    import app as app_module

    email = "qa.member@example.com"
    delete_user(email)
    auth.create_user(email, "QA Member", "member-pass-123", "MEMBER")

    with TestClient(app_module.app) as c:
        c.post(
            "/login",
            data={"email": email, "password": "member-pass-123"},
            follow_redirects=False,
        )
        assert c.cookies.get("session_id"), "MEMBER should be able to log in"

        resp = c.get("/team", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
