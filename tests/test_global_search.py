"""One box across Conversations, Escalations, Knowledge Base and Curated
Answers.

Deep-linking depends on `pin=` reaching outside the normal recent-window cap
and filter on `list_conversations`/`list_handoffs` — those are exercised here
too, since a search result nobody can actually open is worse than no result.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import passwords, permissions
from bankassist.models import Conversation, Handoff, Role, User, UserCredential


def _headers(bank: Any) -> dict[str, str]:
    return {"X-Admin-Token": bank.admin_token}


def _staff(
    client: TestClient, db_session: Any, bank: Any, email: str, role_name: str
) -> TestClient:
    """A separate client signed in as a new person with this role — the
    cookie jar is per-client, so reusing `client` would leave every later
    call under this test carrying the wrong identity."""
    role = db_session.execute(
        select(Role).where(Role.bank_id == bank.id, Role.name == role_name)
    ).scalar_one()
    user = User(bank_id=bank.id, email=email, display_name=email, role_id=role.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    session_client = TestClient(client.app)
    resp = session_client.post(
        f"/admin/api/{bank.slug}/login",
        json={"email": email, "password": "CorrectHorse9!x"},
    )
    assert resp.status_code == 200, resp.text
    return session_client


def _ask(client: TestClient, slug: str, message: str) -> str:
    resp = client.post(f"/chat/{slug}", json={"message": message})
    assert resp.status_code == 200, resp.text
    cid: str = resp.json()["conversation_id"]
    return cid


def _search(caller: TestClient, slug: str, q: str, bank: Any = None) -> dict[str, Any]:
    headers = _headers(bank) if bank is not None else {}
    resp = caller.get(f"/admin/api/{slug}/search", params={"q": q}, headers=headers)
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _create_document(client: TestClient, bank: Any, title: str, content: str) -> str:
    resp = client.post(
        f"/admin/api/{bank.slug}/documents",
        json={"title": title, "content": content, "category": "general", "language": "en"},
        headers=_headers(bank),
    )
    assert resp.status_code == 201, resp.text
    doc_id: str = resp.json()["id"]
    return doc_id


def _create_faq(
    client: TestClient, bank: Any, question: str, answer: str, status: str = "published"
) -> str:
    resp = client.post(
        f"/admin/api/{bank.slug}/faq",
        json={"question": question, "answer": answer, "language": "en", "status": status},
        headers=_headers(bank),
    )
    assert resp.status_code == 201, resp.text
    fid: str = resp.json()["id"]
    return fid


# ------------------------------------------------------------ finds a match


def test_finds_a_conversation_by_message_text(client: TestClient, demo_bank: Any) -> None:
    cid = _ask(client, "demo", "Do you sponsor competitive platypus racing leagues?")
    data = _search(client, "demo", "platypus", bank=demo_bank)
    assert cid in {c["id"] for c in data["conversations"]}


def test_finds_a_handoff_by_its_detail(client: TestClient, demo_bank: Any) -> None:
    cid = _ask(client, "demo", "Do you sponsor competitive narwhal tap-dancing?")
    data = _search(client, "demo", "narwhal", bank=demo_bank)
    assert any(h["conversation_id"] == cid for h in data["handoffs"])


def test_finds_a_document_by_title(client: TestClient, demo_bank: Any) -> None:
    doc_id = _create_document(
        client, demo_bank, "Quokka Savings Account", "Illustrative product content."
    )
    data = _search(client, "demo", "quokka", bank=demo_bank)
    assert doc_id in {d["id"] for d in data["documents"]}


def test_finds_a_document_by_content(client: TestClient, demo_bank: Any) -> None:
    doc_id = _create_document(
        client, demo_bank, "Ordinary Savings", "Only available to registered wombat holders."
    )
    data = _search(client, "demo", "wombat", bank=demo_bank)
    assert doc_id in {d["id"] for d in data["documents"]}


def test_finds_a_faq_by_question_or_answer(client: TestClient, demo_bank: Any) -> None:
    fid = _create_faq(
        client, demo_bank,
        "Can I open an account with a capybara as co-signer?",
        "Only human account holders are eligible.",
    )
    by_question = _search(client, "demo", "capybara", bank=demo_bank)
    assert fid in {f["id"] for f in by_question["faq"]}

    fid2 = _create_faq(
        client, demo_bank,
        "What documents do I need to open an account?",
        "Bring your Fayda ID and proof of ocelot ownership.",
    )
    by_answer = _search(client, "demo", "ocelot", bank=demo_bank)
    assert fid2 in {f["id"] for f in by_answer["faq"]}


def test_matching_is_case_insensitive(client: TestClient, demo_bank: Any) -> None:
    _create_document(client, demo_bank, "Aardvark Loans", "Illustrative content.")
    data = _search(client, "demo", "AARDVARK", bank=demo_bank)
    assert any(d["title"] == "Aardvark Loans" for d in data["documents"])


def test_a_query_under_two_characters_returns_nothing(
    client: TestClient, demo_bank: Any
) -> None:
    data = _search(client, "demo", "a", bank=demo_bank)
    assert data == {"conversations": [], "handoffs": [], "documents": [], "faq": []}


def test_results_are_capped_per_category(client: TestClient, demo_bank: Any) -> None:
    for i in range(7):
        _create_document(client, demo_bank, f"Aye-aye Product {i}", "Illustrative content.")
    data = _search(client, "demo", "aye-aye", bank=demo_bank)
    assert len(data["documents"]) == 5


# --------------------------------------------------------------- redaction


def test_a_conversation_snippet_is_redacted(client: TestClient, demo_bank: Any) -> None:
    """A customer can volunteer a phone number mid-question — the same rule
    the two aggregate reports already follow (`classifier.redact_contact()`
    before a signature or example is built) applies to a search snippet."""
    _ask(
        client, "demo",
        "My number is 0911234567, can you sponsor competitive dachshund limbo?",
    )
    data = _search(client, "demo", "dachshund", bank=demo_bank)
    assert len(data["conversations"]) == 1
    assert "0911234567" not in data["conversations"][0]["snippet"]


# ------------------------------------------------------------ tenant scope


def test_one_banks_search_never_surfaces_anothers_content(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    _create_document(client, demo_bank, "Bandicoot Account", "Illustrative content.")
    data = _search(client, "cbe", "bandicoot", bank=cbe_bank)
    assert data == {"conversations": [], "handoffs": [], "documents": [], "faq": []}


# -------------------------------------------------------- permission scoping


def test_every_builtin_role_can_search(
    client: TestClient, db_session: Any, demo_bank: Any
) -> None:
    """All three builtin roles hold conversations.read, handoffs.read and
    documents.read — the floor this endpoint gates on, plus the two it
    re-checks per category — so none of them should be shut out of the box
    wholesale. Custom roles holding documents.read without the other two are
    what the per-category re-check exists for; the builtin roster has no such
    role to exercise it against."""
    _create_document(client, demo_bank, "Echidna Account", "Illustrative content.")
    for email, role_name in (
        ("op@bank.et", permissions.OPERATOR),
        ("tel@bank.et", permissions.TELLER),
        ("adm@bank.et", permissions.ADMIN),
    ):
        staff = _staff(client, db_session, demo_bank, email, role_name)
        data = _search(staff, "demo", "echidna")
        assert any(d["title"] == "Echidna Account" for d in data["documents"]), role_name


# -------------------------------------------------------------------- pin


def test_pin_includes_a_conversation_outside_the_current_filter(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    cid = _ask(client, "demo", "Hello there")
    convo = db_session.get(Conversation, cid)
    convo.language = "am"
    db_session.commit()

    # A language filter for "en" would ordinarily exclude this conversation.
    resp = client.get(
        "/admin/api/demo/conversations", params={"language": "en", "pin": cid},
        headers=_headers(demo_bank),
    )
    assert resp.status_code == 200, resp.text
    assert cid in {c["id"] for c in resp.json()}


def test_pin_never_crosses_a_tenant_boundary(
    client: TestClient, demo_bank: Any, cbe_bank: Any
) -> None:
    cid = _ask(client, "demo", "Hello there")
    resp = client.get(
        "/admin/api/cbe/conversations", params={"pin": cid}, headers=_headers(cbe_bank)
    )
    assert resp.status_code == 200, resp.text
    assert cid not in {c["id"] for c in resp.json()}


def test_pin_includes_a_handoff_outside_the_status_filter(
    client: TestClient, demo_bank: Any
) -> None:
    cid = _ask(client, "demo", "Do you sponsor competitive pangolin bowling?")
    handoffs = client.get(
        "/admin/api/demo/handoffs", params={"status": "all"}, headers=_headers(demo_bank)
    ).json()
    hid = next(h["id"] for h in handoffs if h["conversation_id"] == cid)
    assert client.post(
        f"/admin/api/demo/handoffs/{hid}/close", headers=_headers(demo_bank)
    ).status_code == 200

    resp = client.get(
        "/admin/api/demo/handoffs", params={"status": "open", "pin": hid},
        headers=_headers(demo_bank),
    )
    assert resp.status_code == 200, resp.text
    assert hid in {h["id"] for h in resp.json()}


def test_pin_never_includes_a_handoff_that_needs_no_person(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    cid = _ask(client, "demo", "Do you sponsor competitive pangolin bowling?")
    row = db_session.execute(
        select(Handoff).where(Handoff.conversation_id == cid)
    ).scalar_one()
    row.needs_person = False
    db_session.commit()

    resp = client.get(
        "/admin/api/demo/handoffs", params={"pin": row.id}, headers=_headers(demo_bank)
    )
    assert resp.status_code == 200, resp.text
    assert row.id not in {h["id"] for h in resp.json()}
