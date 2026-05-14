"""Administrator routes: dashboard, invitations, starter catalog edits."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password, verify_password
from app.models import Invitation, StarterTopic, User


def _admin_login(client: TestClient, db: Session) -> None:
    db.add(User(username="_staff_adm_", password_hash=hash_password("Staff-Pass-77"), is_admin=True))
    db.commit()
    r = client.post("/login", data={"username": "_staff_adm_", "password": "Staff-Pass-77"})
    assert r.status_code == 303


def test_member_blocked_from_admin_home(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "pleb", "password": "pw", "invite_code": register_invite},
    )
    assert client.get("/admin").status_code == 403


def test_admin_dashboard_renders(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"Users" in r.content


def test_create_and_revoke_invitation(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    assert test_db.scalar(select(func.count(Invitation.id))) == 0
    cre = client.post("/admin/invites", follow_redirects=False)
    assert cre.status_code == 303
    loc = cre.headers.get("location") or ""
    assert "created=" in loc

    invitations = list(test_db.scalars(select(Invitation)).all())
    assert len(invitations) == 1
    inv_id = invitations[0].id

    rev = client.post(f"/admin/invites/{inv_id}/revoke", follow_redirects=False)
    assert rev.status_code == 303
    assert test_db.scalar(select(func.count(Invitation.id))) == 0


def test_generate_invitation_creates_second_code(client: TestClient, test_db: Session, register_invite: str):
    """Admin can mint invites after bootstrap invite row exists."""
    _admin_login(client, test_db)
    prior = test_db.scalar(select(func.count(Invitation.id)))
    assert prior >= 1
    r = client.post("/admin/invites", follow_redirects=False)
    assert r.status_code == 303
    assert test_db.scalar(select(func.count(Invitation.id))) == prior + 1


def test_starter_catalog_add_topic_via_form_post(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    assert test_db.scalar(select(func.count(StarterTopic.id))) == 0
    r = client.post("/admin/starter/topics", data={"name": "AdminSeed"}, follow_redirects=False)
    assert r.status_code == 303
    assert test_db.scalar(select(func.count(StarterTopic.id))) == 1


def test_suspend_other_user_via_admin(client: TestClient, test_db: Session, register_invite: str):
    _admin_login(client, test_db)
    inviter_id = test_db.scalars(select(User.id).where(User.username == "_staff_adm_")).one()
    test_db.add(Invitation(code="second-inv-for-suspend", created_by=inviter_id))
    test_db.commit()

    client.post(
        "/register",
        data={"username": "vic", "password": "vicpw", "invite_code": "second-inv-for-suspend"},
    )
    # Registration replaced the session cookie; log back in as staff.
    client.post("/login", data={"username": "_staff_adm_", "password": "Staff-Pass-77"})
    vic_id = test_db.scalars(select(User.id).where(User.username == "vic")).one()
    rsp = client.post(f"/admin/users/{vic_id}/suspend", follow_redirects=False)
    assert rsp.status_code == 303
    test_db.expire_all()
    assert test_db.scalars(select(User.is_suspended).where(User.id == vic_id)).one() is True


def test_admin_password_reset(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    test_db.add(User(username="subj", password_hash=hash_password("old-old"), is_admin=False))
    test_db.commit()
    uid = test_db.scalars(select(User.id).where(User.username == "subj")).one()
    rsp = client.post(
        f"/admin/users/{uid}/password",
        data={"new_password": "fresh-new-strong"},
        follow_redirects=False,
    )
    assert rsp.status_code == 303
    test_db.expire_all()
    row = test_db.scalars(select(User).where(User.id == uid)).one()
    assert verify_password("fresh-new-strong", row.password_hash)
