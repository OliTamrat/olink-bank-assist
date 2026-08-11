"""Delete remote branches whose pull request was merged.

    python scripts/prune_merged_branches.py           # list what would go
    python scripts/prune_merged_branches.py --write   # delete them

Needs `GITHUB_TOKEN` (or `GH_TOKEN`) with repo write. Run it from anywhere
with normal GitHub access — the agent sandbox cannot do this: both the API
path and `git push --delete` are refused by its proxy with a 403, so this
exists to make the job one command rather than a hundred.

**Merged is decided by the pull request, not by ancestry.** This repo
squash-merges, so a merged branch's commits are NOT ancestors of `main` and
`git branch --merged` reports zero of them. Asking the PR is the only answer
that is right here; the ancestry check would either delete nothing or, with
`--no-merged`, delete everything.

Four things it will not touch:

  * the default branch;
  * any branch with an OPEN pull request;
  * any branch whose PR was **closed without merging** — that work exists
    nowhere else, and deleting it is the one mistake in this script that
    could not be undone from the pull request;
  * any branch with no pull request at all, for the same reason.

Dry run by default. It prints the four groups so the decision is visible
before anything is irreversible.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

REPO = "OliTamrat/olink-bank-assist"
API = "https://api.github.com"


def token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(name)
        if value:
            return value
    print("set GITHUB_TOKEN (or GH_TOKEN) to a token with repo write access")
    raise SystemExit(2)


def api(path: str, auth: str, method: str = "GET") -> object:
    req = urllib.request.Request(
        f"{API}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {auth}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status == 204 or method == "DELETE":
            return None
        return json.load(resp)


def paged(path: str, auth: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        got = api(f"{path}{sep}per_page=100&page={page}", auth)
        assert isinstance(got, list)
        out += got
        if len(got) < 100:
            break
        page += 1
    return out


def main(argv: list[str]) -> int:
    write = "--write" in argv
    auth = token()

    repo = api(f"/repos/{REPO}", auth)
    assert isinstance(repo, dict)
    default = str(repo["default_branch"])

    branches = [str(b["name"]) for b in paged(f"/repos/{REPO}/branches", auth)]
    prs: dict[str, list[dict[str, object]]] = {}
    for pr in paged(f"/repos/{REPO}/pulls?state=all", auth):
        head = pr["head"]
        assert isinstance(head, dict)
        prs.setdefault(str(head["ref"]), []).append(pr)

    merged: list[str] = []
    keep_open: list[str] = []
    keep_unmerged: list[str] = []
    keep_no_pr: list[str] = []
    for name in branches:
        if name == default:
            continue
        entries = prs.get(name, [])
        if any(e["state"] == "open" for e in entries):
            keep_open.append(name)
        elif any(e.get("merged_at") for e in entries):
            merged.append(name)
        elif entries:
            keep_unmerged.append(name)
        else:
            keep_no_pr.append(name)

    print(f"{len(branches)} branches, default is {default}\n")
    for label, group in (
        ("KEEP — open pull request", keep_open),
        ("KEEP — closed without merging, the work is only here", keep_unmerged),
        ("KEEP — no pull request ever", keep_no_pr),
    ):
        if group:
            print(f"{label}: {len(group)}")
            for name in group:
                print(f"    {name}")
            print()

    print(f"MERGED, safe to delete: {len(merged)}")
    if not write:
        for name in merged:
            print(f"    {name}")
        print("\nnothing deleted — pass --write")
        return 0

    gone = failed = 0
    for name in merged:
        try:
            api(f"/repos/{REPO}/git/refs/heads/{name}", auth, method="DELETE")
            gone += 1
        except urllib.error.HTTPError as exc:
            failed += 1
            print(f"    ! {name}: HTTP {exc.code} {exc.read().decode()[:120]}")
    print(f"\ndeleted {gone}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
