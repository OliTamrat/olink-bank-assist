"""Emit new seed documents as bulk-import JSON, for tenants that already exist.

Run: `python scripts/export_new_documents.py <commit-range>`
     `python scripts/export_new_documents.py 89e887d..HEAD`

**Seeding does not update a tenant that exists.** `seed_prospect_bank` looks up
the slug, finds a row, and returns before it touches documents at all. That is
deliberate — a seeder that rewrote a live corpus every time it ran would be a
foot-gun pointed at a production tenant — but it means a document added to
`seed_cbe.py` reaches a fresh database and never reaches the four tenants
already in production.

Deploying does not help either: the seed files are code, and the corpus is
data that was written once when the tenant was created.

So the supported route is the one CLAUDE.md already names as the real
onboarding path — `POST /admin/api/{slug}/documents/bulk`, or the paste-a-JSON
card on the admin Knowledge Base screen. This writes the file for that: it
diffs the seed modules against a commit you name, and prints only the
documents that are new, in the exact `{"documents": [...]}` shape the endpoint
takes.

**The import is all-or-nothing** on an unsupported language code — the batch
is rejected whole rather than importing half a knowledge base and leaving the
gaps to be discovered later — so a rejected paste means a bad `language`
field, not a partly-applied corpus.

Nothing here talks to a database or a network. It reads two git revisions of
the seed files and prints JSON, so it is safe to run anywhere and the output
is what you inspect before pasting it into a bank's live tenant.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from typing import Any

SEEDS = {
    "demo": "bankassist/seed.py",
    "cbe": "bankassist/seed_cbe.py",
    "dashen": "bankassist/seed_dashen.py",
    "awash": "bankassist/seed_awash.py",
}


def _docs_at(revision: str, path: str) -> list[dict[str, str]]:
    """The `_DOCS` list as it stood at `revision`.

    Parsed with `ast.literal_eval` over the module's own AST rather than by
    importing it: importing a seed module at two revisions in one process is
    not possible, and executing code from an arbitrary revision to read a list
    of strings is a bad trade.
    """
    try:
        source = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return []

    tree = ast.parse(source)

    # `literal_eval` alone is not enough: seed_cbe.py uses an imported
    # constant as a category value, and a Name node makes it raise. Resolve
    # the handful of names these files actually use, and fall through to the
    # endpoint's own default for anything unrecognised.
    names: dict[str, str] = {}
    try:
        from bankassist.agent import WHY_CHOOSE_CATEGORY

        names["WHY_CHOOSE_CATEGORY"] = WHY_CHOOSE_CATEGORY
    except ImportError:  # pragma: no cover - only if the constant is renamed
        pass
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (isinstance(target, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                names[target.id] = node.value.value

    def literal(node: ast.expr) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return names.get(node.id)
        if isinstance(node, ast.JoinedStr):  # an f-string: not a literal corpus
            return None
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            return None
        return value if isinstance(value, str) else None

    for node in tree.body:
        # Narrowed to the two assignment forms up front, so the `.value`
        # accesses below are on a type that has one.
        if isinstance(node, ast.Assign):
            targets: list[ast.expr] = list(node.targets)
            assigned: ast.expr | None = node.value
        elif isinstance(node, ast.AnnAssign):
            targets, assigned = [node.target], node.value
        else:
            continue
        for target in targets:
            if not (isinstance(target, ast.Name) and target.id == "_DOCS"):
                continue
            if not isinstance(assigned, ast.List):
                continue
            docs: list[dict[str, str]] = []
            for element in assigned.elts:
                if not isinstance(element, ast.Dict):
                    continue
                entry: dict[str, str] = {}
                for key, value in zip(element.keys, element.values, strict=True):
                    if not (isinstance(key, ast.Constant)
                            and isinstance(key.value, str)):
                        continue
                    text = literal(value)
                    if text is not None:
                        entry[key.value] = text
                if entry.get("title") and entry.get("content"):
                    docs.append(entry)
            return docs
    return []


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        print("error: name a commit range, e.g. 89e887d..HEAD", file=sys.stderr)
        return 2

    spec = argv[0]
    before, _, after = spec.partition("..")
    after = after or "HEAD"

    total = 0
    for slug, path in SEEDS.items():
        old = {d["title"] for d in _docs_at(before, path)}
        new = [d for d in _docs_at(after, path) if d["title"] not in old]
        if not new:
            continue
        total += len(new)
        payload: dict[str, Any] = {
            "documents": [
                {
                    "title": d["title"],
                    "content": d["content"],
                    "category": d.get("category", "general"),
                    "language": d.get("language", "en"),
                }
                for d in new
            ]
        }
        out = f"import-{slug}.json"
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        titles = ", ".join(d["title"] for d in new)
        print(f"{out}: {len(new)} document(s) — {titles}")

    if not total:
        print(f"no new documents between {before} and {after}")
        return 0

    print(
        f"\n{total} document(s) across {len(SEEDS)} tenant(s).\n"
        "Paste each file into Knowledge Base -> import on that tenant, or:\n"
        "  curl -X POST <api>/admin/api/<slug>/documents/bulk \\\n"
        "       -H 'Content-Type: application/json' --data @import-<slug>.json\n"
        "Signed in as a user with documents.write — the admin token cannot do\n"
        "this any more (ADR-0031)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
