"""Getting a bank's published material in, at the volume it exists in.

Every tenant runs on fifteen to twenty-three articles. A real bank's website
is several hundred pages, and that gap — not the model, not retrieval, not the
prompt — is the ceiling on what the assistant can answer. The only ways in
were a form that takes one article at a time and a raw JSON paste, which is
why the gap never closed.

Two halves are worth testing hard and they are not the obvious ones. The
extraction has to drop site furniture, because navigation imported onto every
page becomes the highest document-frequency text in the corpus and would make
retrieval worse with each page added. And the URL fetch is server-side request
forgery by construction: an authenticated operator makes OUR server fetch an
address they typed, one hop from a metadata service that hands out the
service account's token to anything that asks.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from bankassist import ingest
from bankassist.models import Document

PAGE = """
<html><head><title>Savings | Demo Bank</title></head>
<body>
  <nav><a href="/">Home</a><a href="/loans">Loans</a></nav>
  <header><h1>Demo Bank</h1></header>
  <main>
    <h2>Ordinary Savings Account</h2>
    <p>Open an ordinary savings account at any branch with your Fayda ID.</p>
    <p>The minimum opening balance is 100 birr and interest is paid quarterly
       at seven percent per year on the average daily balance.</p>
    <ul><li>No monthly maintenance fee</li><li>Free first debit card</li></ul>
    <h2>Fixed Time Deposit</h2>
    <!-- Furniture INSIDE a section, which is where it actually appears on a
         real page: in-body sidebars, tracking snippets, and the "back to top"
         link at the end of a long article. An earlier version of this fixture
         only had furniture before the first heading and after the last, so
         neither filter was ever exercised — two mutation tests survived that
         should not have. -->
    <p>A fixed deposit locks your money for a chosen term of three, six or
       twelve months in exchange for a higher rate of interest than an
       ordinary savings account pays.</p>
    <aside><a href="/loans">Explore our loans</a></aside>
    <script>gtag('event', 'view');</script>
    <p>Early withdrawal forfeits the accrued interest for the whole period.</p>
    <p>Back to top</p>
    <p>Share</p>
    <h2>Careers</h2>
    <p>Apply here.</p>
  </main>
  <footer><p>© 2026 Demo Bank</p><p>Privacy Policy</p></footer>
  <script>var tracker = 1;</script>
</body></html>
"""


# ------------------------------------------------------------- extraction


def test_a_page_becomes_one_document_per_heading() -> None:
    """A bank's page about savings accounts is one topic with one name, and
    that name is what `suggest_topics` offers somebody who phrased their
    question differently. Chopping it into "part 3 of 7" would fill the
    near-miss list with fragments nobody asked for."""
    found = ingest.sections(PAGE)
    assert [s.title for s in found] == [
        "Ordinary Savings Account", "Fixed Time Deposit"
    ]


def test_a_stub_section_is_not_worth_a_document() -> None:
    """"Careers — apply here" is a heading with a link under it. Importing it
    adds a title to the suggestion list that answers nothing when a customer
    picks it."""
    assert "Careers" not in [s.title for s in ingest.sections(PAGE)]


def test_site_furniture_never_becomes_content() -> None:
    """The failure that would be attributed to anything but the import.
    Navigation and footers appear on every page, so importing them makes them
    the highest document-frequency text in the corpus — BM25 correctly rates
    them worthless, the informativeness gate then treats every page as mostly
    noise, and retrieval gets WORSE with each page added."""
    body = " ".join(s.body for s in ingest.sections(PAGE)).lower()
    for furniture in (
        "home", "privacy policy", "tracker", "© 2026",
        # These three sit INSIDE a section in the fixture, which is where they
        # sit on a real page. Without them here the block stripper and the
        # line filter were both untested: everything else was before the first
        # heading or after the last, so it was never inside a section body at
        # all, and a mutation removing either filter passed.
        "explore our loans", "gtag", "back to top",
    ):
        assert furniture not in body, furniture


def test_paragraphs_survive_as_paragraphs() -> None:
    """Not cosmetic. `retrieval.chunk_text` splits on blank lines, so a
    converter that returned one long line would produce one enormous chunk per
    page and destroy retrieval precision on everything imported."""
    first = ingest.sections(PAGE)[0]
    assert "\n\n" in first.body


def test_list_items_are_kept() -> None:
    """"No monthly maintenance fee" is exactly the sort of thing a customer
    asks about, and it only ever appears in a list."""
    body = ingest.sections(PAGE)[0].body
    assert "No monthly maintenance fee" in body


def test_a_page_with_no_headings_still_imports() -> None:
    """Returning nothing for such a page would silently drop content a bank
    believes it imported — an import that reports success and leaves a hole is
    the worst outcome available here."""
    plain = (
        "<html><head><title>Tariff</title></head><body><p>" + "Fees apply. " * 30
        + "</p></body></html>"
    )
    found = ingest.sections(plain)
    assert len(found) == 1
    assert found[0].title == "Tariff"


def test_entities_are_decoded() -> None:
    markup = "<h2>Fees &amp; Charges</h2><p>" + "The charge is 5 birr. " * 12 + "</p>"
    assert ingest.sections(markup)[0].title == "Fees & Charges"


# ------------------------------------------------------------------- ssrf


@pytest.mark.parametrize("url", [
    "http://cbe.com.et/",                       # plain http
    "https://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://127.0.0.1/",
    "https://localhost/admin",
    "https://10.1.2.3/",
    "https://172.20.0.1/",
    "https://192.168.0.1/",
    "https://100.100.100.200/",                 # carrier-grade NAT
    "https://user:secret@cbe.com.et/",
    "https://[::1]/",
    "https://intranet/",
    "https://0.0.0.0/",
])
def test_an_unsafe_address_is_refused(url: str) -> None:
    """On Cloud Run the thing worth stealing is one hop away: the metadata
    service hands out the service account's access token to anything that
    asks. An import feature that fetches whatever it is given is a
    credential-exfiltration endpoint with a friendly name."""
    with pytest.raises(ingest.UnsafeUrl):
        ingest.check_url(url)


@pytest.mark.parametrize("url", [
    "https://www.cbe.com.et/personal/savings",
    "https://dashenbanksc.com/loans/",
    "https://awashbank.com/en/accounts?tab=2",
])
def test_a_real_bank_address_is_allowed(url: str) -> None:
    """The other half. A guard that refuses everything is a feature nobody can
    use, and the temptation is then to relax it in a hurry."""
    assert ingest.check_url(url) == url


def test_the_endpoint_refuses_an_unsafe_address(
    client: TestClient, demo_bank: Any
) -> None:
    """Enforced on the route, not only in the module — a check nothing calls
    is a comment."""
    resp = client.post(
        "/admin/api/demo/ingest/preview",
        json={"url": "https://169.254.169.254/"},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 422, resp.text


# -------------------------------------------------------- preview & commit


def _preview(client: TestClient, bank: Any, **kw: Any) -> Any:
    resp = client.post(
        "/admin/api/demo/ingest/preview",
        json={"html": PAGE, **kw},
        headers={"X-Admin-Token": bank.admin_token},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_previewing_writes_nothing(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Nobody should write two hundred documents into the thing that answers
    their customers on the strength of a URL typed into a box."""
    before = len(db_session.execute(select(Document)).scalars().all())
    body = _preview(client, demo_bank)
    assert [s["title"] for s in body["sections"]] == [
        "Ordinary Savings Account", "Fixed Time Deposit"
    ]
    db_session.expire_all()
    assert len(db_session.execute(select(Document)).scalars().all()) == before


def test_only_the_ticked_sections_are_written(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """The first page a bank imports always brings a section they do not want.
    An import that wrote everything it found is the reason nobody would use it
    twice."""
    resp = client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": PAGE, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"created": 1, "updated": 0}
    titles = {
        d.title for d in db_session.execute(select(Document)).scalars().all()
    }
    assert "Fixed Time Deposit" in titles
    assert "Ordinary Savings Account" not in titles


def test_re_importing_an_updated_page_replaces_rather_than_duplicates(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """A knowledge base holding last quarter's fee beside this quarter's, with
    nothing to say which is current, gives the customer whichever one scores
    higher. That is worse than not importing at all."""
    client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": PAGE, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    changed = PAGE.replace("higher rate of interest", "MUCH higher rate of interest")
    resp = client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": changed, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    assert resp.json() == {"created": 0, "updated": 1}

    db_session.expire_all()
    rows = db_session.execute(
        select(Document).where(Document.title == "Fixed Time Deposit")
    ).scalars().all()
    assert len(rows) == 1
    assert "MUCH higher" in rows[0].content


def test_the_preview_says_which_ones_would_be_replaced(
    client: TestClient, demo_bank: Any
) -> None:
    """Re-importing an updated page has to read as "five updates", not as five
    unexplained duplicates about to appear."""
    client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": PAGE, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    body = _preview(client, demo_bank)
    by_title = {s["title"]: s for s in body["sections"]}
    assert by_title["Fixed Time Deposit"]["replaces"] is True
    assert by_title["Ordinary Savings Account"]["replaces"] is False


def test_imported_content_is_searchable_immediately(
    client: TestClient, demo_bank: Any
) -> None:
    """The point of the whole feature. An import that needs a redeploy before
    it answers anything is a data-entry exercise."""
    assert "forfeits" not in client.post(
        "/chat/demo", json={"message": "What happens if I withdraw a fixed deposit early?"}
    ).json()["reply"]

    client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": PAGE, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    reply = client.post(
        "/chat/demo",
        json={"message": "What happens if I withdraw a fixed deposit early?"},
    ).json()["reply"]
    assert "forfeit" in reply.lower()


def test_importing_is_audited(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Content a bank's assistant quotes to customers arrived from somewhere,
    and "somebody pasted it" is not an answer a compliance reviewer accepts."""
    from bankassist.models import AuditLog

    client.post(
        "/admin/api/demo/ingest/commit",
        json={"html": PAGE, "titles": ["Fixed Time Deposit"]},
        headers={"X-Admin-Token": demo_bank.admin_token},
    )
    row = db_session.execute(
        select(AuditLog).where(AuditLog.action == "documents_imported")
    ).scalars().first()
    assert row is not None and row.log_metadata["created"] == 1


def test_importing_needs_permission_to_write_documents(
    client: TestClient, demo_bank: Any, db_session: Any
) -> None:
    """Same bar as editing the knowledge base by hand, because it is the same
    act at a hundred times the speed."""
    from bankassist import passwords, permissions
    from bankassist.models import Role, User, UserCredential

    role = db_session.execute(
        select(Role).where(Role.bank_id == demo_bank.id, Role.name == permissions.TELLER)
    ).scalar_one()
    user = User(
        bank_id=demo_bank.id, email="t@bank.et", display_name="T", role_id=role.id
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
    client.post(
        "/admin/api/demo/login",
        json={"email": "t@bank.et", "password": "CorrectHorse9!x"},
    )
    assert client.post(
        "/admin/api/demo/ingest/commit", json={"html": PAGE, "titles": []}
    ).status_code == 403
