"""Retrieve (or rotate) a tenant's admin token.

The seed scripts deliberately stop short of printing the token under CI, so
this is the supported way to get one for the admin panel. Rotation exists
because a token that has been read out of a build log, pasted into a chat, or
mailed to a colleague should be replaceable without re-seeding the tenant.

    python -m bankassist.show_token cbe
    python -m bankassist.show_token cbe --rotate
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .db import get_engine, init_db
from .models import Bank, new_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bankassist.show_token")
    parser.add_argument("slug", help="bank slug, e.g. demo, cbe, dashen, awash")
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="issue a new token, invalidating the current one immediately",
    )
    args = parser.parse_args(argv)

    init_db()
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as db:
        bank = db.execute(select(Bank).where(Bank.slug == args.slug)).scalar_one_or_none()
        if bank is None:
            print(f"No bank with slug {args.slug!r}", file=sys.stderr)
            return 1
        if args.rotate:
            bank.admin_token = new_token()
            db.commit()
            print(f"Rotated. The previous token for {bank.name} no longer works.")
        print(f"{bank.name} (slug={bank.slug})")
        print(f"Admin token: {bank.admin_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
