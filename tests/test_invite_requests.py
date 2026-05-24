"""Public invitation request form and admin review queue."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password
from app.invite_requests import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from app.models import Invitation, InvitationRequest, User


def _admin_login(client: TestClient, db: Session) -> None:
    db.add(User(username="_staff_adm_", password_hash=hash_password("Staff-Pass-77"), is_admin=True))
    db.commit()
    r = client.post("/login", data={"username": "_staff_adm_", "password": "Staff-Pass-77"})
    assert r.status_code == 303


def _submit_request(
    client: TestClient,
    *,
    email: str = "alice@example.com",
    name: str = "Alice",
    message: str = "I build CLI tools.",
    website: str = "",
) -> TestClient:
    return client.post(
        "/request-invite",
        data={
            "email": email,
            "name": name,
            "message": message,
            "website": website,
        },
    )


def test_request_invite_get_renders_form(client: TestClient, test_db: Session):
    r = client.get("/request-invite")
    assert r.status_code == 200
    assert b"Request an invitation" in r.content
    assert b'name="email"' in r.content


def test_request_invite_post_creates_pending_row(client: TestClient, test_db: Session):
    r = _submit_request(client)
    assert r.status_code == 200
    assert b"alice@example.com" in r.content
    row = test_db.scalars(select(InvitationRequest)).one()
    assert row.email == "alice@example.com"
    assert row.name == "Alice"
    assert row.message == "I build CLI tools."
    assert row.status == STATUS_PENDING


def test_request_invite_post_duplicate_pending_email(client: TestClient, test_db: Session):
    _submit_request(client)
    r = _submit_request(client, name="", message="")
    assert r.status_code == 400
    assert b"pending request" in r.content.lower()
    assert test_db.scalar(select(func.count(InvitationRequest.id))) == 1


def test_request_invite_post_honeypot_discards_without_db_row(client: TestClient, test_db: Session):
    r = _submit_request(client, website="https://spam.example")
    assert r.status_code == 200
    assert b"Thanks" in r.content
    assert test_db.scalar(select(func.count(InvitationRequest.id))) == 0


def test_request_invite_get_redirects_logged_in_user(
    client: TestClient,
    test_db: Session,
    register_invite: str,
):
    client.post(
        "/register",
        data={"username": "member", "password": "pw-longer", "invite_code": register_invite},
    )
    r = client.get("/request-invite")
    assert r.status_code == 303
    assert r.headers.get("location") == "/"


def test_login_page_links_to_request_invite(client: TestClient, test_db: Session):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"/request-invite" in r.content


def test_member_blocked_from_admin_invite_requests(
    client: TestClient,
    test_db: Session,
    register_invite: str,
):
    client.post(
        "/register",
        data={"username": "pleb", "password": "pw-longer", "invite_code": register_invite},
    )
    assert client.get("/admin/invite-requests").status_code == 403


def test_admin_approve_creates_invitation(client: TestClient, test_db: Session):
    _submit_request(client)
    req = test_db.scalars(select(InvitationRequest)).one()
    _admin_login(client, test_db)
    r = client.post(f"/admin/invite-requests/{req.id}/approve", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers.get("location") or ""
    assert "approved=" in loc
    assert "created=" in loc

    test_db.refresh(req)
    assert req.status == STATUS_APPROVED
    assert req.invitation_id is not None
    inv = test_db.get(Invitation, req.invitation_id)
    assert inv is not None
    assert inv.used_by is None


def test_admin_approve_non_pending_redirects_with_error(client: TestClient, test_db: Session):
    _submit_request(client)
    req = test_db.scalars(select(InvitationRequest)).one()
    req.status = STATUS_REJECTED
    test_db.commit()
    _admin_login(client, test_db)
    r = client.post(f"/admin/invite-requests/{req.id}/approve", follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in (r.headers.get("location") or "")


def test_admin_reject_sets_status_without_invitation(client: TestClient, test_db: Session):
    _submit_request(client)
    req = test_db.scalars(select(InvitationRequest)).one()
    _admin_login(client, test_db)
    r = client.post(f"/admin/invite-requests/{req.id}/reject", follow_redirects=False)
    assert r.status_code == 303
    test_db.refresh(req)
    assert req.status == STATUS_REJECTED
    assert req.invitation_id is None
    assert test_db.scalar(select(func.count(Invitation.id))) == 0


def test_admin_invite_requests_page_shows_register_link_after_approve(
    client: TestClient,
    test_db: Session,
):
    _submit_request(client)
    req = test_db.scalars(select(InvitationRequest)).one()
    _admin_login(client, test_db)
    client.post(f"/admin/invite-requests/{req.id}/approve", follow_redirects=True)
    r = client.get("/admin/invite-requests")
    assert r.status_code == 200
    assert b"/register?code=" in r.content
