#!/usr/bin/env python
"""Read the leads the agent has captured.

    uv run python scripts/leads.py                 # last 20
    uv run python scripts/leads.py --since 7d
    uv run python scripts/leads.py --json

Email notification is the thing that reaches you in the moment; this is the
durable record, for when you want to look back over everything.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from core import config, db  # noqa: E402

_SINCE_RE = re.compile(r"^(\d+)([hdw])$")


def _parse_since(value: str) -> datetime:
    m = _SINCE_RE.match(value.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("Use forms like 24h, 7d, 2w")
    amount, unit = int(m.group(1)), m.group(2)
    delta = {"h": timedelta(hours=amount),
             "d": timedelta(days=amount),
             "w": timedelta(weeks=amount)}[unit]
    return datetime.now(timezone.utc) - delta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--since", type=_parse_since, help="e.g. 24h, 7d, 2w")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if not config.DATABASE_URL:
        print("DATABASE_URL is not set — no lead store configured.", file=sys.stderr)
        return 1

    from sqlalchemy import select

    query = select(db.leads_table).order_by(db.leads_table.c.created_at.desc())
    if args.since:
        query = query.where(db.leads_table.c.created_at >= args.since)
    query = query.limit(args.limit)

    try:
        with db.get_engine().connect() as conn:
            rows = [dict(r._mapping) for r in conn.execute(query)]
    except Exception as e:
        print(f"Could not read leads: {e}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(rows, indent=2, default=str))
        return 0

    if not rows:
        print("No leads yet.")
        return 0

    for row in rows:
        when = row["created_at"].strftime("%Y-%m-%d %H:%M") if row["created_at"] else "?"
        print(f"\n#{row['id']}  {when}  via {row['source'] or '?'}")
        print(f"  {row['name'] or '(no name)'} <{row['email'] or 'no email'}>")
        if row["company"]:
            print(f"  Company: {row['company']}")
        if row["intent"]:
            print(f"  Intent:  {row['intent']}")
        if row["message"]:
            print(f"  Message: {row['message']}")
        if row["booking_uid"]:
            print(f"  Booked:  {row['booking_uid']}")

    print(f"\n{len(rows)} lead(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
