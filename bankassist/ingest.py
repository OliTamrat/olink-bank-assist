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

# How much of a block's text may sit inside links before it is navigation
# rather than prose.
#
# From the first real import. A CBE page returned exactly one section — a
# related-services widget reading "Mobile Banking / Easy to use / Go Ahead /
# CBE Cards" — because it happened to sit under an h2 and cleared the length
# floor by seven characters. Length alone cannot tell a short article from a
# list of links, and the tell is that almost every word is a link label.
#
# Half is deliberately generous. Real articles link freely — a savings page
# links to the account-opening form and to three other products — and the
# blocks this is aimed at are 80–100% anchor text.
MAX_LINK_RATIO: Final = 0.5

# The longest unbroken run of text a block must contain to count as something
# written to be read.
#
# The link ratio alone did not catch the CBE block: its card blurbs — "Easy to
# use", "Shop, travel, and pay easily" — are not links, so only 37% of it was
# anchor text and it sailed through. What actually distinguishes it is that
# NOTHING in it is a sentence. A card grid is a pile of fragments; an article
# has at least one run of prose.
#
# 60 characters is about a short sentence. A section that cannot manage one
# is a feature list or a menu, and if a bank wants it in the knowledge base
# they can add it by hand — which is the right side to err on, because the
# cost of importing a menu is that it competes with real answers in every
# search from then on.
MIN_PROSE_RUN: Final = 60

# A navigation strip as it survives a copy-paste.
#
# Selecting a rendered page collapses the whole menu onto one line —
# "Home Personal Business Diaspora About Contact" — which the line-by-line
# furniture list cannot catch, because every entry in that list is a SINGLE
# word and this is six of them. Seen immediately on the first pasted page,
# where it became the opening sentence of the imported article and therefore
# the first thing the assistant quoted back.
#
# Four capitalised words with no sentence punctuation between them. A real
# sentence has a verb and a full stop; a heading is one or two words. Four is
# the point where "several nouns in a row" stops being either.
_NAV_STRIP: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Z][^\s.,:;?!]*\s+){3,}[A-Z][^\s.,:;?!]*$"
)


def longest_run(text: str) -> int:
    """The longest single line, which is the best available proxy for "is
    any of this a sentence"."""
    return max((len(line.strip()) for line in text.splitlines()), default=0)

_ANCHOR: Final = re.compile(r"<a\b[^>]*>(.*?)</a\s*>", re.IGNORECASE | re.DOTALL)


def link_ratio(markup: str) -> float:
    """What fraction of this block's visible text is link labels.

    Zero for a block with no links and no text, which reads as "not
    navigation" — the length floor is what rejects those.
    """
    total = len(to_text(markup))
    if not total:
        return 0.0
    linked = sum(len(to_text(m.group(1))) for m in _ANCHOR.finditer(markup))
    return min(1.0, linked / total)


# A call to action, on its own line. Always noise, in every context.
#
# "Click here to register now!" and "Seize this opportunity today!" answer no
# question anybody will ever ask, and a customer who asked about remittance
# fees does not want one quoted back at them. Dropped rather than flagged,
# because unlike the marketing TONE of a page — which is a judgement — a bare
# call to action is measurably not an answer.
_CTA_LINE: Final[re.Pattern[str]] = re.compile(
    r"^(?:click here.*|seize this opportunity.*|don'?t miss out.*|"
    r"(?:sign up|register|apply|join|order|subscribe|download)"
    r"(?: now| today| here)?[!.]?|"
    r"(?:get started|learn more|find out more|read more|discover more|"
    r"contact us today|call us now|visit us today)[!.]?|"
    r"(?:partner|bank) with us today[!.]?)$",
    re.IGNORECASE,
)

# Marketing vocabulary. NOT used to drop anything — used to flag a section so
# an operator importing two hundred pages sees the sales copy without reading
# every one.
#
# Filtering on this would be wrong. Every bank product page is somewhat
# promotional, and "Open a savings account today and earn 7% interest" is both
# marketing and the literal answer to "what interest do you pay". The
# judgement of whether a page belongs in a knowledge base is the bank's; the
# job here is to make that judgement fast.
_MARKETING: Final[re.Pattern[str]] = re.compile(
    # Possessive-agnostic throughout. The first real page said "increase
    # THEIR revenue" and "expand THEIR business" — it is addressed to agents
    # about their own customers — and a pattern written only for "your" scored
    # it as ordinary prose. Marketing copy switches person freely depending on
    # who it is aimed at; the vocabulary is what stays constant.
    r"\b(earn more|maximi[sz]e (your|their)|seize this|don'?t miss|"
    r"limited time|act now|hurry|exclusive offer|special offer|"
    r"opportunity to (earn|grow|expand|seize)|boost (your|their)|"
    r"unlock (your|their)|(grow|expand) (your|their) business|"
    r"increase (your|their) (revenue|profit|income)|"
    r"why wait|today only|register now|sign up today)\b",
    re.IGNORECASE,
)

# How many marketing markers before a section is flagged. Two, not one: a
# single "grow your business" inside a page about business accounts is
# ordinary product writing, and flagging it would train an operator to ignore
# the flag.
MARKETING_MARKERS: Final = 2


def marketing_markers(text: str) -> int:
    """How many pieces of sales language this section contains."""
    return len(_MARKETING.findall(text))


def is_promotional(title: str, body: str) -> bool:
    """Whether to flag this as sales copy. Never a reason to drop it.

    Title AND body. The strongest signal is almost always the headline — "Earn
    More by Partnering with CBE" is the whole giveaway on a page whose prose
    then reads like an ordinary product description — and scoring the body
    alone missed exactly that page.
    """
    text = f"{title}\n{body}"
    return marketing_markers(text) >= MARKETING_MARKERS or text.count("!") >= 3


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
        if _FURNITURE.match(line) or _CTA_LINE.match(line):
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
        raw = markup[start:end]
        body = to_text(raw)
        if not heading or len(body) < MIN_SECTION_CHARS:
            continue
        # Two ways of being a menu rather than an article, and the CBE block
        # that prompted both was only caught by the second: mostly link
        # labels, or nothing in it long enough to be a sentence.
        if link_ratio(raw) > MAX_LINK_RATIO:
            continue
        if longest_run(body) < MIN_PROSE_RUN:
            continue
        out.append(Section(title=heading[:MAX_TITLE_CHARS], body=body))
    return out


def looks_like_markup(text: str) -> bool:
    """Whether this is HTML or something a person selected and copied.

    A page that builds itself in the browser cannot be imported from its
    source, and telling an operator to dig HTML out of the developer tools is
    a instruction most people will not follow. Selecting the page and copying
    it is the thing everybody can do — so plain text has to be a first-class
    input, not a failure.

    Shape rather than a strict parse: two angle-bracketed tags is enough to be
    markup, and prose that happens to contain "<" is not.
    """
    return len(re.findall(r"<[a-zA-Z/!][^>]*>", text)) >= 2


def plain_text_section(text: str, title: str) -> list[Section]:
    """One section from copied text, under a title the operator supplies.

    No heading detection. Copied text has lost the structure that headings
    live in, and guessing which lines were headings would produce documents
    titled "Go Ahead" — which is exactly the failure that made this necessary.
    The chunker still splits it for retrieval, so a long page is not one
    enormous chunk.
    """
    kept: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [
            _SPACES.sub(" ", line).strip()
            for line in block.splitlines()
            if line.strip()
        ]
        lines = [
            line for line in lines
            if not _FURNITURE.match(line)
            and not _NAV_STRIP.match(line)
            and not _CTA_LINE.match(line)
        ]
        if lines:
            kept.append("\n".join(lines))
    body = "\n\n".join(kept)
    if len(body) < MIN_SECTION_CHARS:
        return []
    return [Section(title=(title.strip() or "Imported page")[:MAX_TITLE_CHARS], body=body)]


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


# ------------------------------------------------------------- diagnosis
#
# "Nothing importable on that page" is true and useless. The operator is
# standing in front of a page they can SEE has content, being told there is
# none, with no idea whether to try a different page, a different button, or
# give up on the feature. What they need is which of the three it is.

# Below this, a page that is mostly markup is a shell waiting for JavaScript
# to fill it. A real article page is text-heavy even with modern markup; 2% is
# far under anything a served page produces and well over an empty shell.
_TEXT_RATIO_FLOOR: Final = 0.02


def diagnose(markup: str, found: list[Section]) -> str | None:
    """Why an import came back thin, in words an operator can act on.

    None when there is nothing to explain. Never speculative: each branch is
    something measurable about the markup we actually received, not a guess
    about the site.
    """
    if found:
        return None
    text = to_text(markup)
    if not markup.strip():
        return "That page returned nothing at all."
    if len(text) < 400 and len(text) / max(len(markup), 1) < _TEXT_RATIO_FLOOR:
        # The shape of a single-page app: kilobytes of scripts and containers,
        # almost no words. Fetching harder will not help — the words do not
        # exist until a browser runs the page.
        return (
            "This page builds its content in the browser, so there is nothing "
            "to read in what the server sends. Open it, press F12, right-click "
            "the <html> line and choose Copy → Copy outerHTML, then paste "
            "that here. (View Source will not work — it shows the same empty "
            "shell we received.)"
        )
    if not _SECTION_RE.search(markup):
        return (
            "That page has no headings to split on, and too little text to "
            "import as one article. Try a product or FAQ page rather than a "
            "landing page."
        )
    return (
        "Every section on that page was too short, or was a list of links "
        "rather than something to read. Landing pages usually look like this "
        "— try the page a customer would actually read."
    )
