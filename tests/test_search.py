"""Full-text search, FTS sync hooks, and auto-generated index."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.auth import hash_password
from app.indexing import extract_action, fts_insert
from app.models import Entry, Section, Topic, User


@pytest.fixture
def notebook_section(authenticated_client: TestClient, test_db: Session) -> Section:
    authenticated_client.post("/topics", data={"name": "K8s"})
    topic = test_db.scalars(select(Topic).where(Topic.name == "K8s")).one()
    authenticated_client.post(f"/topics/{topic.id}/sections", data={"name": "Pods"})
    return test_db.scalars(
        select(Section).where(Section.topic_id == topic.id, Section.name == "Pods"),
    ).one()


def test_extract_action_maps_remove_delete() -> None:
    assert extract_action("Remove a container") == "delete"
    assert extract_action("Delete a branch") == "delete"


def test_search_returns_results(notebook_section: Section, authenticated_client: TestClient) -> None:
    uniq = "searchneedle_zed_441"
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": f"List {uniq} resources", "command": "kubectl get pods"},
    )
    r = authenticated_client.get("/search", params={"q": uniq})
    assert r.status_code == 200
    assert uniq.encode("utf-8") in r.content
    assert b"search-results-wrap" in r.content


def test_search_page_has_duckai_link(authenticated_client: TestClient) -> None:
    r = authenticated_client.get("/search")
    assert r.status_code == 200
    assert b'https://duck.ai/' in r.content
    assert b"Find new commands with Duck.ai" in r.content


def test_search_empty_query(notebook_section: Section, authenticated_client: TestClient) -> None:
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": "Something", "command": "cmd"},
    )
    r = authenticated_client.get("/search", params={"q": "   "})
    assert r.status_code == 200
    assert b"search-results-wrap" not in r.content
    assert b"Type a search phrase" not in r.content


def test_search_htmx_empty_query_clears_results(authenticated_client: TestClient) -> None:
    r = authenticated_client.get(
        "/search",
        params={"q": ""},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert not r.content.strip()


def test_search_htmx_partial(notebook_section: Section, authenticated_client: TestClient) -> None:
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": "Echo partial marker", "command": "partial-cmd-mark"},
    )
    r = authenticated_client.get(
        "/search",
        params={"q": "partial"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert b"<html" not in r.content.lower()
    assert b"search-results" in r.content


def test_nav_search_htmx_dropdown_is_compact_command_links(
    notebook_section: Section,
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    """Nav bar live search uses a list of command links, not the wide results table."""
    topic = test_db.scalars(select(Topic).where(Topic.id == notebook_section.topic_id)).one()
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={
            "description": "Reset branch example",
            "command": "git checkout main",
        },
    )
    r = authenticated_client.get(
        "/search",
        params={"q": "checkout", "view": "nav"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert b"nav-search-results__list" in r.content
    assert b"git checkout main" in r.content
    assert f'href="/topic/{topic.slug}#entry-row-'.encode("utf-8") in r.content
    assert b"entry-table" not in r.content
    assert b"DESCRIPTION" not in r.content


def test_nav_search_duckai_link_in_navbar(authenticated_client: TestClient) -> None:
    r = authenticated_client.get("/")
    assert r.status_code == 200
    assert b'id="nav-search-live"' in r.content
    assert b'https://duck.ai/' in r.content
    assert b"Find new commands with Duck.ai" in r.content
    assert b'id="nav-search-results"' in r.content


def test_nav_search_empty_query_clears_results_only(authenticated_client: TestClient) -> None:
    r = authenticated_client.get(
        "/search",
        params={"q": "", "view": "nav"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert not r.content.strip()


def test_search_no_cross_user_leakage(
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    secret = "leak_guard_alpha_993"
    authenticated_client.post("/topics", data={"name": "OwnerTopic"})
    owner_topic = test_db.scalars(select(Topic).where(Topic.name == "OwnerTopic")).one()
    authenticated_client.post(f"/topics/{owner_topic.id}/sections", data={"name": "S1"})
    sec = test_db.scalars(
        select(Section).where(Section.topic_id == owner_topic.id, Section.name == "S1"),
    ).one()
    authenticated_client.post(
        f"/sections/{sec.id}/entries",
        data={"description": f"Mine {secret}", "command": "x"},
    )

    other = User(username="other searcher", password_hash=hash_password("pw"))
    test_db.add(other)
    test_db.flush()
    ot = Topic(user_id=other.id, name="Other", slug="other", display_order=0)
    test_db.add(ot)
    test_db.flush()
    os_section = Section(topic_id=ot.id, name="SX", display_order=0)
    test_db.add(os_section)
    test_db.flush()
    test_db.add(
        Entry(
            section_id=os_section.id,
            description=f"Their notebook {secret} entry",
            command="other-cmd",
            display_order=0,
        ),
    )
    test_db.flush()
    other_entry = test_db.scalars(
        select(Entry).where(Entry.section_id == os_section.id).order_by(Entry.id.desc()),
    ).first()
    assert other_entry is not None
    fts_insert(
        test_db,
        other_entry.id,
        other_entry.description,
        other_entry.command,
    )
    test_db.commit()

    r = authenticated_client.get("/search", params={"q": secret})
    assert r.status_code == 200
    body = r.text
    assert f"Mine {secret}" in body
    assert "Their notebook " not in body


def test_fts_sync_on_create(notebook_section: Section, authenticated_client: TestClient) -> None:
    token = "fts_create_token_bb"
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": f"Describe {token}", "command": "noop"},
    )
    r = authenticated_client.get("/search", params={"q": token})
    assert r.status_code == 200
    assert token.encode("utf-8") in r.content


def test_fts_sync_on_update(
    notebook_section: Section,
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    old_t = "old_match_cc"
    new_t = "new_match_dd"
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": f"Was {old_t}", "command": "c"},
    )
    entry = test_db.scalars(
        select(Entry).where(Entry.section_id == notebook_section.id, Entry.description.contains(old_t)),
    ).one()

    authenticated_client.put(
        f"/entries/{entry.id}",
        data={"description": f"Now {new_t}", "command": "c"},
    )
    r_old = authenticated_client.get("/search", params={"q": old_t})
    assert r_old.status_code == 200
    assert b"search-results-wrap" not in r_old.content
    r_new = authenticated_client.get("/search", params={"q": new_t})
    assert r_new.status_code == 200
    assert b"search-results-wrap" in r_new.content


def test_fts_sync_on_delete(
    notebook_section: Section,
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    gone = "deleted_token_ee"
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": f"Holds {gone}", "command": "c"},
    )
    entry = test_db.scalars(
        select(Entry).where(Entry.section_id == notebook_section.id, Entry.description.contains(gone)),
    ).one()
    authenticated_client.delete(f"/entries/{entry.id}")
    r = authenticated_client.get("/search", params={"q": gone})
    assert r.status_code == 200
    assert b"search-results-wrap" not in r.content


def test_index_page_loads(notebook_section: Section, authenticated_client: TestClient) -> None:
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": "List backups", "command": "restic snapshots"},
    )
    r = authenticated_client.get("/index")
    assert r.status_code == 200
    assert b'class="index-shell"' in r.content
    assert b"List backups" in r.content
    assert b'data-index-jump' in r.content
    assert b'id="index-top"' in r.content
    assert b'href="#index-top"' in r.content
    assert b'href="#index-letter-L"' in r.content
    assert b'index-back-top' in r.content


def test_index_one_table_sorted_by_description_first_word(
    notebook_section: Section,
    authenticated_client: TestClient,
) -> None:
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": "Build containers", "command": "docker build ."},
    )
    authenticated_client.post(
        f"/sections/{notebook_section.id}/entries",
        data={"description": "Bake an image locally", "command": "podman-local"},
    )
    r = authenticated_client.get("/index")
    assert r.status_code == 200
    assert r.text.count("entry-table index-table") == 1
    assert "index-action__label" not in r.text
    bake_idx = r.text.index("Bake an image locally")
    build_idx = r.text.index("Build containers")
    assert bake_idx < build_idx


def test_index_requires_auth(client: TestClient) -> None:
    r = client.get("/index", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_search_requires_auth(client: TestClient) -> None:
    r = client.get("/search", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_search_finds_orphan_db_rows_without_fts_row(
    notebook_section: Section,
    authenticated_client: TestClient,
    test_db: Session,
) -> None:
    """LIKE-based search matches ``entries`` even when ``entries_fts`` was never updated."""
    orphan_token = "like_orphan_marker_q7"
    test_db.add(
        Entry(
            section_id=notebook_section.id,
            description=f"Orphan {orphan_token}",
            command="orphan-cmd",
            display_order=99,
        ),
    )
    test_db.commit()

    r = authenticated_client.get("/search", params={"q": orphan_token})
    assert r.status_code == 200
    assert orphan_token.encode("utf-8") in r.content
    assert b"search-results-wrap" in r.content
