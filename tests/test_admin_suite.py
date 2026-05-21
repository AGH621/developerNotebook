"""Administrator routes: dashboard, invitations, starter catalog edits."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password, verify_password
from app.models import AppSettings, Invitation, StarterEntry, StarterSection, StarterTopic, User
from app.settings import SETTINGS_ROW_ID, invalidate_settings_cache


def _admin_login(client: TestClient, db: Session) -> None:
    db.add(User(username="_staff_adm_", password_hash=hash_password("Staff-Pass-77"), is_admin=True))
    db.commit()
    r = client.post("/login", data={"username": "_staff_adm_", "password": "Staff-Pass-77"})
    assert r.status_code == 303


def test_member_blocked_from_admin_home(client: TestClient, test_db: Session, register_invite: str):
    client.post(
        "/register",
        data={"username": "pleb", "password": "pw-longer", "invite_code": register_invite},
    )
    assert client.get("/admin").status_code == 403


def test_admin_dashboard_renders(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"Users" in r.content
    assert b"Session timeouts" in r.content


def test_admin_updates_session_timeouts(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    r = client.post(
        "/admin/settings/session-timeouts",
        data={"session_absolute_minutes": "120", "session_idle_minutes": "30"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "ok=" in (r.headers.get("location") or "")
    invalidate_settings_cache()
    settings = test_db.get(AppSettings, SETTINGS_ROW_ID)
    assert settings is not None
    assert settings.session_absolute_minutes == 120
    assert settings.session_idle_minutes == 30


def test_admin_rejects_invalid_session_timeouts(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    r = client.post(
        "/admin/settings/session-timeouts",
        data={"session_absolute_minutes": "10", "session_idle_minutes": "30"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in (r.headers.get("location") or "")


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


def test_invites_page_includes_copy_buttons(client: TestClient, test_db: Session):
    _admin_login(client, test_db)
    client.post("/admin/invites", follow_redirects=True)
    r = client.get("/admin/invites")
    assert r.status_code == 200
    assert b'data-copy-text="' in r.content
    assert b"copy-btn admin-copy-btn" in r.content
    assert b"/register?code=" in r.content


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
    tid = test_db.scalars(select(StarterTopic.id)).one()
    assert (r.headers.get("location") or "").strip() == f"/admin/starter#admin-starter-topic-{tid}"
    assert test_db.scalar(select(func.count(StarterTopic.id))) == 1


def test_starter_topic_and_section_form_redirects_match_anchors(
    client: TestClient,
    test_db: Session,
    starter_catalog: None,
):
    _admin_login(client, test_db)
    topic = test_db.scalars(select(StarterTopic).order_by(StarterTopic.id)).first()
    assert topic is not None

    save_topic = client.post(
        f"/admin/starter/topics/{topic.id}/save",
        data={"name": topic.name},
        follow_redirects=False,
    )
    assert save_topic.status_code == 303
    assert (save_topic.headers.get("location") or "").strip() == (
        f"/admin/starter#admin-starter-topic-{topic.id}"
    )

    add_sec = client.post(
        f"/admin/starter/topics/{topic.id}/sections",
        data={"name": "Extra admin section"},
        follow_redirects=False,
    )
    assert add_sec.status_code == 303
    loc_sec = (add_sec.headers.get("location") or "").strip()
    assert loc_sec.startswith("/admin/starter#admin-starter-section-")
    new_sec_id = int(loc_sec.split("admin-starter-section-", 1)[1])

    sec_row = test_db.get(StarterSection, new_sec_id)
    assert sec_row is not None
    assert sec_row.topic_id == topic.id

    del_sec = client.post(f"/admin/starter/sections/{new_sec_id}/delete", follow_redirects=False)
    assert del_sec.status_code == 303
    assert (del_sec.headers.get("location") or "").strip() == (
        f"/admin/starter#admin-starter-topic-{topic.id}"
    )

    del_topic = client.post(f"/admin/starter/topics/{topic.id}/delete", follow_redirects=False)
    assert del_topic.status_code == 303
    assert (del_topic.headers.get("location") or "").strip() == "/admin/starter#admin-starter-catalog"


def test_starter_catalog_page_has_jump_navigation(client: TestClient, test_db: Session, starter_catalog: None):
    _admin_login(client, test_db)
    topics = list(test_db.scalars(select(StarterTopic)).all())
    assert topics

    rsp = client.get("/admin/starter")
    assert rsp.status_code == 200
    html = rsp.text
    assert "admin-starter-jump" in html

    m = re.search(r'class="admin-starter-jump__list"(.*?)</ul>', html, re.DOTALL)
    assert m is not None
    nav_ids = [int(x) for x in re.findall(r'href="#admin-starter-topic-(\d+)"', m.group(1))]
    assert len(nav_ids) == len(topics)
    assert set(nav_ids) == {t.id for t in topics}
    by_alpha = sorted(topics, key=lambda t: (t.name.casefold(), t.id))
    assert nav_ids == [t.id for t in by_alpha]


def test_starter_add_command_redirect_targets_new_entry_anchor(
    client: TestClient,
    test_db: Session,
    starter_catalog: None,
):
    """Adding a starter command uses a plain form POST → 303 to #admin-starter-entry-{id}."""
    _admin_login(client, test_db)
    sec_id = test_db.scalars(select(StarterSection.id).order_by(StarterSection.id)).first()
    assert sec_id is not None

    rsp = client.post(
        f"/admin/starter/sections/{sec_id}/entries",
        data={"description": "Scroll test line", "command": "scroll-test-cmd"},
        follow_redirects=False,
    )
    assert rsp.status_code == 303
    loc = (rsp.headers.get("location") or "").strip()
    prefix = "/admin/starter#admin-starter-entry-"
    assert loc.startswith(prefix)
    frag_id_str = loc.removeprefix(prefix)
    assert frag_id_str.isdigit()
    ent_id = int(frag_id_str)
    ent_row = test_db.get(StarterEntry, ent_id)
    assert ent_row is not None
    assert ent_row.section_id == sec_id
    assert ent_row.description == "Scroll test line"


def test_starter_save_entry_redirect_targets_entry_anchor(
    client: TestClient,
    test_db: Session,
    starter_catalog: None,
):
    _admin_login(client, test_db)
    ent_row = test_db.scalars(select(StarterEntry).order_by(StarterEntry.id)).first()
    assert ent_row is not None

    rsp = client.post(
        f"/admin/starter/entries/{ent_row.id}/save",
        data={"description": "Updated via save", "command": ent_row.command},
        follow_redirects=False,
    )
    assert rsp.status_code == 303
    assert (rsp.headers.get("location") or "").strip() == (
        f"/admin/starter#admin-starter-entry-{ent_row.id}"
    )
    test_db.refresh(ent_row)
    assert ent_row.description == "Updated via save"


def test_starter_delete_command_redirect_targets_section_anchor(
    client: TestClient,
    test_db: Session,
    starter_catalog: None,
):
    """After deleting a starter command, redirect scrolls to the parent section."""
    _admin_login(client, test_db)
    sec_id = test_db.scalars(select(StarterSection.id).order_by(StarterSection.id)).first()
    assert sec_id is not None

    add = client.post(
        f"/admin/starter/sections/{sec_id}/entries",
        data={"description": "Row to remove", "command": "gone"},
        follow_redirects=False,
    )
    assert add.status_code == 303
    hx_add = (add.headers.get("location") or "").strip()
    ent_id = int(hx_add.removeprefix("/admin/starter#admin-starter-entry-"))

    delrsp = client.post(
        f"/admin/starter/entries/{ent_id}/delete",
        follow_redirects=False,
    )
    assert delrsp.status_code == 303
    assert (delrsp.headers.get("location") or "").strip() == (
        f"/admin/starter#admin-starter-section-{sec_id}"
    )
    assert test_db.get(StarterEntry, ent_id) is None

    add2 = client.post(
        f"/admin/starter/sections/{sec_id}/entries",
        data={"description": "Another", "command": "y"},
        follow_redirects=False,
    )
    assert add2.status_code == 303
    ent2_id = int(
        (add2.headers.get("location") or "")
        .removeprefix("/admin/starter#admin-starter-entry-")
        .strip(),
    )
    r2 = client.post(f"/admin/starter/entries/{ent2_id}/delete", follow_redirects=False)
    assert r2.status_code == 303
    assert (r2.headers.get("location") or "").endswith(f"#admin-starter-section-{sec_id}")


def test_suspend_other_user_via_admin(client: TestClient, test_db: Session, register_invite: str):
    _admin_login(client, test_db)
    inviter_id = test_db.scalars(select(User.id).where(User.username == "_staff_adm_")).one()
    test_db.add(Invitation(code="second-inv-for-suspend", created_by=inviter_id))
    test_db.commit()

    client.post(
        "/register",
        data={"username": "vic", "password": "vicpass-long", "invite_code": "second-inv-for-suspend"},
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
