"""Turning a bank's published material into knowledge-base documents.

Every tenant is running on fifteen to twenty-three articles. A real bank's
public website is several hundred pages, and that gap — not the model, not the
retrieval, not the prompt — is the ceiling on what the assistant can answer.
The only ways in today are a form that takes one article at a time and a raw
JSON paste, which is why the gap has not closed.

This module is the pure half: HTML in, proposed documents out. No database, no
network, no dependencies. The parts that touch the world live in `api.py`, and
they are deliberately thin, because the interesting failures here are all in
what gets *decided* rather than in what gets fetched.

---

**Split on headings, not on length.** A bank's page about savings accounts is
one topic with one name, and that name is what `suggest_topics` offers a
customer who phrased something differently. Chopping a page into "Savings
Accounts (part 3 of 7)" would fill the near-miss suggestions with fragments
nobody asked for. So each h1/h2 becomes one document titled by its heading,
and the existing chunker splits it for retrieval afterwards — which is where
length belongs.

**Boilerplate is dropped before anything else.** Navigation, cookie banners
and footers appear on every page of a site, which makes them the highest
document-frequency text in the corpus the moment they are imported. BM25 would
correctly rate them worthless, and the informativeness gate would then treat
every page as mostly noise — the import would make retrieval WORSE, page by
page, in a way nobody would attribute to the import.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from dataclasses import dataclass
from typing import Final

# Elements whose contents are never content. `nav`, `header`, `footer` and
# `aside` are the site furniture; `script`, `style`, `noscript`, `svg`, `form`
# and `template` are not prose at all and would arrive as a wall of tokens.
_STRIP_BLOCKS: Final[tuple[str, ...]] = (
    "script", "style", "noscript", "svg", "template", "form", "iframe",
    "nav", "header", "footer", "aside", "button", "select",
)

_COMMENT: Final = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG: Final = re.compile(r"<[^>]+>")
_SPACES: Final = re.compile(r"[ \t ]+")
_BLANKS: Final = re.compile(r"\n{3,}")

# Headings that start a new document, and the ones that stay inside it. h3 and
# below are sub-points of the section they sit in — promoting them would turn
# one article into a dozen stubs, each too short to answer anything.
_SECTION_RE: Final = re.compile(r"<h([12])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)

# What separates one block of prose from the next once the tags are gone.
_BLOCK_END: Final = re.compile(
    r"</(p|div|section|article|li|tr|h[1-6]|blockquote|td|th)\s*>",
    re.IGNORECASE,
)
_BREAK: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_LIST_ITEM: Final = re.compile(r"<li\b[^>]*>", re.IGNORECASE)

# Lines that are navigation or legal furniture rather than something a
# customer asked about. Matched on the WHOLE line, so an article that happens
# to discuss cookies or contains the word "menu" is untouched.
_FURNITURE: Final = re.compile(
    r"^(home|menu|search|login|log in|sign in|sign up|register|close|skip to "
    r"(main )?content|back to top|share|print|previous|next|read more|"
    r"cookie[s]?( policy| settings| preferences)?|accept( all)?( cookies)?|"
    r"privacy policy|terms( and conditions| of use)?|all rights reserved|"
    r"follow us|copyright.*|©.*)$",
    re.IGNORECASE,
)

# A section shorter than this is a stub — a heading with a link under it, or a
# card on a landing page. Importing it adds a title to the suggestion list
# that answers nothing when a customer picks it.
MIN_SECTION_CHARS: Final = 120

# Longer than this and it is a whole page that never got a second heading.
# Kept rather than dropped: the chunker will split it for retrieval, and a
# long article is a real thing a bank publishes.
MAX_TITLE_CHARS: Final = 200


@dataclass(frozen=True)
class Section:
    """One proposed document: a heading and the prose under it."""

    title: str
    body: str

    @property
    def chars(self) -> int:
        return len(self.body)


def _unescape(text: str) -> str:
    return unicodedata.normalize("NFKC", html_module.unescape(text))


def _drop_blocks(markup: str) -> str:
    out = markup
    for tag in _STRIP_BLOCKS:
        out = re.sub(
            rf"<{tag}\b[^>]*>.*?</{tag}\s*>", " ", out,
            flags=re.IGNORECASE | re.DOTALL,
        )
        # Unclosed or self-closing forms of the same tags, which real pages are
        # full of. Without this a single stray <nav> swallows nothing and the
        # menu arrives as content.
        out = re.sub(rf"<{tag}\b[^>]*/?>", " ", out, flags=re.IGNORECASE)
    return out


def to_text(markup: str) -> str:
    """HTML to readable text, keeping paragraph boundaries.

    Paragraph boundaries are not cosmetic here: `retrieval.chunk_text` splits
    on blank lines, so a converter that returned one long line would produce
    one enormous chunk per page and destroy retrieval precision.
    """
    text = _COMMENT.sub(" ", markup)
    text = _drop_blocks(text)
    text = _BREAK.sub("\n", text)
    text = _LIST_ITEM.sub("\n• ", text)
    text = _BLOCK_END.sub("\n\n", text)
    text = _TAG.sub(" ", text)
    text = _unescape(text)

    lines = []
    for raw in text.split("\n"):
        line = _SPACES.sub(" ", raw).strip()
        if not line:
            lines.append("")
            continue
        if _FURNITURE.match(line):
            continue
        lines.append(line)
    return _BLANKS.sub("\n\n", "\n".join(lines)).strip()


def sections(markup: str, *, fallback_title: str = "") -> list[Section]:
    """Split a page into one proposed document per h1/h2.

    A page with no headings at all becomes a single section under
    `fallback_title` — usually the page's own <title> or its URL. Returning
    nothing for such a page would silently drop content a bank believes it
    imported, which is the worst outcome available here: an import that
    reports success and leaves a hole.
    """
    found = list(_SECTION_RE.finditer(markup))
    if not found:
        body = to_text(markup)
        title = fallback_title.strip() or page_title(markup) or "Untitled page"
        return (
            [Section(title=title[:MAX_TITLE_CHARS], body=body)]
            if len(body) >= MIN_SECTION_CHARS else []
        )

    out: list[Section] = []
    for i, match in enumerate(found):
        heading = to_text(match.group(2)).strip()
        start = match.end()
        end = found[i + 1].start() if i + 1 < len(found) else len(markup)
        body = to_text(markup[start:end])
        if not heading or len(body) < MIN_SECTION_CHARS:
            continue
        out.append(Section(title=heading[:MAX_TITLE_CHARS], body=body))
    return out


def page_title(markup: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", markup, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    # Sites suffix every title with the bank's name — "Savings Accounts | CBE".
    # Left alone: it is only ever the fallback for a page with no headings,
    # and inventing a rule to strip suffixes would eventually eat a real title.
    return _SPACES.sub(" ", _unescape(match.group(1))).strip()


# ------------------------------------------------------------ fetching safely
#
# This feature lets an authenticated operator make OUR SERVER fetch a URL they
# typed. That is server-side request forgery by construction, and on Cloud Run
# the thing worth stealing is one hop away: http://169.254.169.254/ hands out
# the service account's access token to anything that asks. An import feature
# that fetches whatever it is given is a credential-exfiltration endpoint with
# a friendly name.
#
# So the guard is a allowlist of what a bank's public website can possibly be,
# not a denylist of what an attacker might type. It is pure and separately
# tested, because it is the part where being wrong is expensive and the part
# that cannot be checked by looking at the feature working.

class UnsafeUrl(ValueError):
    """The URL is not something we will fetch. Raised rather than returning a
    flag: every call site must refuse, and a boolean nobody checked is how
    this class of bug ships."""


def check_url(url: str) -> str:
    """The URL to fetch, or raise `UnsafeUrl`.

    Deliberately strict, and each rule earns its place:

    - **https only.** A bank's published material is on https; plain http both
      permits a downgrade and is the scheme every metadata service speaks.
    - **No credentials in the URL.** `https://user:pass@host` is a way to make
      a fetch look like it goes somewhere it does not.
    - **No IP literals, private or otherwise.** A bank's website has a name. A
      literal is either an internal target or an attempt to dodge a hostname
      check, and neither is worth supporting.
    - **No localhost by name**, which is the same target spelled differently.

    What this does NOT do is re-resolve DNS after the check — a hostname that
    resolves to a private address still gets through. Closing that means
    resolving here and pinning the connection to the resolved address, which
    the HTTP client has to cooperate with. It is written down as a known limit
    rather than left as an assumption, and the size and redirect caps at the
    call site are what bound the damage in the meantime.
    """
    raw = url.strip()
    if not raw.lower().startswith("https://"):
        raise UnsafeUrl("Only https:// addresses can be imported")
    rest = raw[len("https://"):]
    if "@" in rest.split("/", 1)[0]:
        raise UnsafeUrl("Addresses with credentials in them are not accepted")
    host = rest.split("/", 1)[0].split(":", 1)[0].strip().lower()
    if not host:
        raise UnsafeUrl("That address has no host")
    if host in ("localhost", "localhost.localdomain") or host.endswith(".localhost"):
        raise UnsafeUrl("That address points at this server")
    # ANY IP literal, not a list of private ranges.
    #
    # There was a private-range check here — 10/8, 172.16/12, 169.254/16, the
    # usual list — and a mutation test proved it was dead: every address it
    # caught was already caught by this rule, because a private address is a
    # dotted quad and so is a public one. Dead security code is worse than
    # none, because the next person may weaken the rule that IS doing the work
    # believing the redundant one has their back. Refusing every literal is
    # both stricter and simpler, and costs nothing: a bank's website has a
    # name.
    if host.count(":") >= 1 or host.startswith("["):
        raise UnsafeUrl("Import a website address, not an IP address")
    if all(p.isdigit() for p in host.split(".")) and host.count(".") == 3:
        raise UnsafeUrl("Import a website address, not an IP address")
    if "." not in host:
        raise UnsafeUrl("That does not look like a public website address")
    return raw
