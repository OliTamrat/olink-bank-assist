"""Language and expertise routing for the queue.

The interesting cases are all about what routing must NOT do: strand the one
customer nobody speaks to, hide work from a teller, or empty every queue on
the day it ships because nobody has declared a language yet.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import teller as t

AM, EN, OM = "am", "en", "om"


# ------------------------------------------------------------------ speaks


def test_an_undeclared_teller_speaks_everything() -> None:
    """Every teller starts undeclared. The opposite reading would empty every
    queue the day this ships and look like an outage, not a feature."""
    assert t.speaks(None, AM) is True
    assert t.speaks([], AM) is True


def test_a_declared_teller_matches_their_own_languages() -> None:
    assert t.speaks([AM, EN], AM) is True
    assert t.speaks([AM, EN], OM) is False


def test_a_session_with_no_language_yet_matches_anybody() -> None:
    """Nothing to route on. Holding it back would be worse than offering it
    — the customer is waiting either way."""
    assert t.speaks([AM], None) is True


# ------------------------------------------------------------------- order


def test_a_matching_customer_is_offered_first() -> None:
    # (language, waited_seconds) — the English one waited longer.
    order = t.queue_order([(EN, None, 40), (AM, None, 10)], [AM])
    assert order == [1, 0]


def test_oldest_first_still_holds_inside_a_group() -> None:
    """Language reorders across groups, never within one. Anything else and
    the person who has waited longest keeps losing, which is what a queue
    exists to prevent."""
    order = t.queue_order([(AM, None, 10), (AM, None, 50), (AM, None, 30)], [AM])
    assert order == [1, 2, 0]


def test_an_undeclared_teller_gets_a_plain_oldest_first_queue() -> None:
    order = t.queue_order([(AM, None, 10), (OM, None, 50), (EN, None, 30)], None)
    assert order == [1, 2, 0]


def test_nobody_is_starved_by_a_language_they_do_not_speak() -> None:
    """The failure this guards is the cruel one: an Oromo speaker sitting
    behind an endless supply of Amharic customers, watching every teller take
    someone else. Past PATIENCE their wait outranks any match.
    """
    long_wait = t.PATIENCE + 1
    order = t.queue_order([(AM, None, 5), (OM, None, long_wait)], [AM])
    assert order[0] == 1


def test_two_starving_customers_are_still_oldest_first() -> None:
    """Once both are past patience, language stops mattering entirely and the
    longest wait wins — otherwise the tie-break would quietly reintroduce the
    starvation this rule exists to remove."""
    order = t.queue_order(
        [(AM, None, t.PATIENCE + 10), (OM, None, t.PATIENCE + 90)], [AM]
    )
    assert order == [1, 0]


def test_a_match_still_wins_below_the_patience_threshold() -> None:
    """Guards the boundary from the other side: patience must not be so eager
    that it cancels routing for every real queue."""
    order = t.queue_order([(EN, None, t.PATIENCE - 1), (AM, None, 0)], [AM])
    assert order == [1, 0]


def test_patience_is_a_realistic_wait() -> None:
    """A threshold of a few seconds would make routing decorative; one of an
    hour would make starvation real. Named so the tradeoff is visible."""
    assert 60 <= t.PATIENCE <= 900


def test_routing_returns_every_session_it_was_given() -> None:
    """Routing changes the ORDER work is offered in, never what is permitted.
    A hard filter would strand the one customer nobody can serve — the
    opposite of what routing them is for.
    """
    sessions = [(AM, None, 10), (OM, None, 20), (EN, None, 30), (None, None, 40)]
    order = t.queue_order(sessions, [AM])
    assert sorted(order) == list(range(len(sessions)))


def test_an_empty_queue_is_not_an_error() -> None:
    assert t.queue_order([], [AM]) == []


# ------------------------------------------------------- over the real queue


def test_the_queue_is_ordered_for_the_teller_who_is_looking(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The same queue is a different order for an Amharic speaker than for an
    Afaan Oromoo one, which is why the order is computed per request rather
    than stored."""
    from bankassist import passwords, permissions
    from bankassist.models import Conversation, Role, User, UserCredential

    def queue_a_customer(language: str) -> str:
        cid = client.post(
            "/chat/demo", json={"message": "Hello"}
        ).json()["conversation_id"]
        convo = db_session.get(Conversation, cid)
        convo.language = language
        db_session.commit()
        sid: str = client.post(
            "/chat/demo/teller-session", json={"conversation_id": cid}
        ).json()["id"]
        return sid

    english = queue_a_customer("en")
    amharic = queue_a_customer("am")

    role = db_session.execute(
        select(Role).where(Role.bank_id == demo_bank.id, Role.name == permissions.TELLER)
    ).scalar_one()
    user = User(
        bank_id=demo_bank.id, email="am@bank.et", display_name="Meron",
        role_id=role.id,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    assert client.post(
        "/admin/api/demo/login",
        json={"email": "am@bank.et", "password": "CorrectHorse9!x"},
    ).status_code == 200

    # Undeclared: plain oldest-first, so the English customer who arrived
    # first is on top.
    rows = client.get("/admin/api/demo/teller/queue").json()
    assert [r["id"] for r in rows] == [english, amharic]
    assert all(r["speaks"] for r in rows), "undeclared speaks everything"

    assert client.put(
        "/admin/api/demo/teller/languages", json={"languages": ["am"]}
    ).status_code == 200

    rows = client.get("/admin/api/demo/teller/queue").json()
    assert [r["id"] for r in rows] == [amharic, english]
    assert {r["id"]: r["speaks"] for r in rows} == {amharic: True, english: False}


def test_a_teller_cannot_claim_a_language_the_product_does_not_support(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Refused rather than dropped: silently ignoring a code would leave a
    teller believing they are routed work they will never be offered."""
    from bankassist import passwords, permissions
    from bankassist.models import Role, User, UserCredential

    role = db_session.execute(
        select(Role).where(Role.bank_id == demo_bank.id, Role.name == permissions.TELLER)
    ).scalar_one()
    user = User(bank_id=demo_bank.id, email="t@bank.et", role_id=role.id)
    db_session.add(user)
    db_session.flush()
    db_session.add(
        UserCredential(
            user_id=user.id, kind="password",
            secret_hash=passwords.hash_password("CorrectHorse9!x"),
        )
    )
    db_session.commit()
    client.post(
        "/admin/api/demo/login",
        json={"email": "t@bank.et", "password": "CorrectHorse9!x"},
    )
    resp = client.put("/admin/api/demo/teller/languages", json={"languages": ["fr"]})
    assert resp.status_code == 422, resp.text
