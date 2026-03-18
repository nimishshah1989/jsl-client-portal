"""
Reset client credentials based on their name.

Derives username and password from cpp_clients.name using the convention:
  - Username: firstnamelastname (lowercase, no spaces)
  - Password: lastnamefirstname (lowercase, no spaces)

Name parsing rules:
  - 3+ word names: first word = firstname, last word = lastname, middle(s) ignored
  - 2-word names:  first = firstname, second = lastname
  - 1-word names:  username = name.lower(), password = name.lower()

Duplicate usernames are resolved by appending an incrementing integer suffix
(e.g., jayeshgolwala → jayeshgolwala2 → jayeshgolwala3).

Admin accounts (is_admin = true) are never modified.

Usage (inside Docker container):
    python3 /app/scripts/reset_credentials.py

Flags:
    --dry-run   Print planned changes without writing to DB.
    --commit    Apply changes to DB (required to actually write; safety gate).

Example:
    docker exec client-portal python3 /app/scripts/reset_credentials.py --dry-run
    docker exec client-portal python3 /app/scripts/reset_credentials.py --commit
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

# Allow imports from project root regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.middleware.auth_middleware import hash_password
from backend.models.client import Client

# ── Separator line width for console output ───────────────────────────────────
_LINE = "-" * 72


def _clean_name_part(part: str) -> str:
    """
    Strip a name word down to ASCII-safe lowercase letters only.

    Handles:
      - Unicode accents (e.g., é → e) via ASCII encode/decode
      - Dots, hyphens, apostrophes stripped (O'Brien → obrien)
      - Any residual non-alpha characters removed
    """
    # Normalise unicode → closest ASCII equivalent where possible
    try:
        ascii_approx = part.encode("ascii", errors="ignore").decode("ascii")
    except Exception:
        ascii_approx = part

    # Keep only letters
    letters_only = re.sub(r"[^a-zA-Z]", "", ascii_approx)
    return letters_only.lower()


def _parse_name(full_name: str) -> tuple[str, str]:
    """
    Split full_name into (firstname, lastname) tokens using the rules:
      - Tokenise on whitespace
      - Ignore empty tokens
      - 3+ words: first token = firstname, last token = lastname
      - 2 words:  first = firstname, second = lastname
      - 1 word:   both firstname and lastname = that word

    Returns (firstname_clean, lastname_clean) as lowercase alpha-only strings.
    Raises ValueError if the name is entirely empty or produces empty tokens
    after cleaning.
    """
    raw_tokens = [t.strip() for t in full_name.split() if t.strip()]

    if not raw_tokens:
        raise ValueError(f"Name is empty or whitespace: {full_name!r}")

    if len(raw_tokens) == 1:
        clean = _clean_name_part(raw_tokens[0])
        if not clean:
            raise ValueError(f"Name produces no usable characters: {full_name!r}")
        return clean, clean

    # 2-word or 3+-word: first and last token
    firstname = _clean_name_part(raw_tokens[0])
    lastname = _clean_name_part(raw_tokens[-1])

    if not firstname:
        raise ValueError(
            f"First name token '{raw_tokens[0]}' produces no usable characters "
            f"in: {full_name!r}"
        )
    if not lastname:
        raise ValueError(
            f"Last name token '{raw_tokens[-1]}' produces no usable characters "
            f"in: {full_name!r}"
        )

    return firstname, lastname


def _derive_credentials(full_name: str) -> tuple[str, str]:
    """
    Return (username_base, plain_password) from the client's full name.

    Multi-word names:
        username_base = firstnamelastname   (may need deduplication later)
        plain_password = lastnamefirstname

    Single-word names (only one token after splitting):
        username_base = name.lower()
        plain_password = name.lower()
    """
    raw_tokens = [t.strip() for t in full_name.split() if t.strip()]

    if len(raw_tokens) == 1:
        # Single-word name: username == password == the cleaned word
        clean = _clean_name_part(raw_tokens[0])
        if not clean:
            raise ValueError(
                f"Name produces no usable characters: {full_name!r}"
            )
        return clean, clean

    firstname, lastname = _parse_name(full_name)
    username_base = firstname + lastname
    plain_password = lastname + firstname
    return username_base, plain_password


def _assign_unique_username(
    username_base: str,
    seen: dict[str, int],
) -> str:
    """
    Return a unique username by appending a counter if the base is taken.

    `seen` maps username_base → next available suffix integer.
    The first occurrence gets no suffix; subsequent ones get 2, 3, … .

    Mutates `seen` in place.
    """
    count = seen.get(username_base, 0)
    if count == 0:
        final = username_base
    else:
        final = f"{username_base}{count + 1}"
    seen[username_base] = count + 1
    return final


async def _load_clients(session) -> list[Client]:
    """Fetch all non-admin clients ordered by id."""
    stmt = (
        select(Client)
        .where(Client.is_admin.is_(False))
        .order_by(Client.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_plan(
    clients: list[Client],
) -> tuple[list[dict], list[dict]]:
    """
    Compute the full credential reset plan.

    Returns:
        changes  — list of dicts describing every update to apply
        errors   — list of dicts for clients that could not be processed
    """
    # Track username bases seen so far to detect duplicates
    seen_bases: dict[str, int] = {}

    changes: list[dict] = []
    errors: list[dict] = []

    for client in clients:
        try:
            username_base, plain_password = _derive_credentials(client.name)
        except ValueError as exc:
            errors.append(
                {
                    "client_id": client.id,
                    "client_code": client.client_code,
                    "name": client.name,
                    "error": str(exc),
                }
            )
            continue

        new_username = _assign_unique_username(username_base, seen_bases)

        changes.append(
            {
                "client": client,
                "client_id": client.id,
                "client_code": client.client_code,
                "name": client.name,
                "old_username": client.username,
                "new_username": new_username,
                "plain_password": plain_password,
                "is_duplicate": new_username != username_base,
            }
        )

    return changes, errors


def _print_plan(changes: list[dict], errors: list[dict]) -> None:
    """Pretty-print the planned changes and any errors to stdout."""
    print(_LINE)
    print("JSL Client Portal — Credential Reset Plan")
    print(_LINE)
    print(f"  Clients to update : {len(changes)}")
    print(f"  Clients with errors: {len(errors)}")
    print()

    if errors:
        print("ERRORS — the following clients will be SKIPPED:")
        for e in errors:
            print(
                f"  [id={e['client_id']:>4}] {e['client_code']:<12} "
                f"'{e['name']}' — {e['error']}"
            )
        print()

    if changes:
        duplicates = [c for c in changes if c["is_duplicate"]]
        print(f"Changes ({len(changes)} clients):")
        print(
            f"  {'ID':>4}  {'Code':<12}  {'Name':<35}  "
            f"{'Old Username':<25}  {'New Username':<25}  Password"
        )
        print(
            f"  {'':->4}  {'':->12}  {'':->35}  "
            f"{'':->25}  {'':->25}  {'':->20}"
        )
        for c in changes:
            dup_marker = " *" if c["is_duplicate"] else "  "
            print(
                f"  {c['client_id']:>4}  {c['client_code']:<12}  "
                f"{c['name'][:35]:<35}  "
                f"{c['old_username']:<25}  "
                f"{c['new_username']:<25}  "
                f"{c['plain_password']}{dup_marker}"
            )
        print()

        if duplicates:
            print(
                f"  * {len(duplicates)} duplicate username(s) — "
                "numeric suffix applied (jayeshgolwala2, etc.)"
            )
            print()

    print(_LINE)


async def _apply_changes(session, changes: list[dict]) -> int:
    """
    Write the planned credential updates to the database.

    Hashes each password with bcrypt cost-12 before storing.
    Returns the number of rows updated.
    """
    updated = 0
    for change in changes:
        client: Client = change["client"]
        client.username = change["new_username"]
        client.password_hash = hash_password(change["plain_password"])
        session.add(client)
        updated += 1

    await session.flush()
    return updated


async def main(dry_run: bool, commit: bool) -> None:
    """Entry point: plan, display, and optionally apply credential resets."""

    if not dry_run and not commit:
        print(
            "ERROR: You must specify --dry-run or --commit.\n"
            "  --dry-run : preview changes without touching the database\n"
            "  --commit  : apply changes permanently\n"
        )
        sys.exit(1)

    if dry_run and commit:
        print("ERROR: Specify either --dry-run or --commit, not both.")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        # Load clients
        clients = await _load_clients(session)
        print(f"Loaded {len(clients)} non-admin client(s) from database.")
        print()

        if not clients:
            print("Nothing to do.")
            return

        # Build plan
        changes, errors = _build_plan(clients)

        # Display plan
        _print_plan(changes, errors)

        if dry_run:
            print("DRY RUN — no changes written. Re-run with --commit to apply.")
            print()
            return

        # Confirm before writing
        print(
            f"About to update credentials for {len(changes)} client(s). "
            "This cannot be undone via this script."
        )
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Aborted — no changes made.")
            return

        try:
            updated = await _apply_changes(session, changes)
            await session.commit()
        except Exception:
            await session.rollback()
            print("ERROR: Database write failed — all changes rolled back.")
            raise

        print()
        print(_LINE)
        print(f"Done. Updated credentials for {updated} client(s).")
        if errors:
            print(f"Skipped {len(errors)} client(s) due to unparseable names (see above).")
        print(_LINE)
        print()
        print(
            "REMINDER: Plain-text passwords were printed above. "
            "Distribute them to clients securely and clear your terminal history."
        )
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reset all non-admin client credentials derived from their name.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview all planned changes without touching the database.",
    )
    mode.add_argument(
        "--commit",
        action="store_true",
        help="Apply credential updates permanently (asks for confirmation).",
    )
    args = parser.parse_args()

    asyncio.run(main(dry_run=args.dry_run, commit=args.commit))
