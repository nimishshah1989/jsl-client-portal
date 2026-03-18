"""
Bulk credential generator for JSL Client Portfolio Portal.

Reads a CSV of client info, generates usernames and random passwords,
outputs a CSV with credentials (plain + hashed) for:
  - Plain passwords: share with clients via WhatsApp
  - Hashed passwords: insert directly into cpp_clients table

Usage:
    python scripts/generate_credentials.py input.csv output.csv

Input CSV columns (required):
    client_code, name

Input CSV columns (optional):
    email, phone

Output CSV adds:
    username, password, password_hash
"""

import csv
import secrets
import string
import sys
from pathlib import Path

# Add project root for passlib import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passlib.hash import bcrypt as bcrypt_hash

BCRYPT_ROUNDS = 12
PASSWORD_LENGTH = 10
PASSWORD_CHARS = string.ascii_letters + string.digits + "!@#$"

REQUIRED_COLUMNS = {"client_code", "name"}


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    """Generate a random password with letters, digits, and special characters."""
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$"),
    ]
    remaining = length - len(password)
    password.extend(secrets.choice(PASSWORD_CHARS) for _ in range(remaining))
    # Shuffle to avoid predictable pattern
    shuffled = list(password)
    secrets.SystemRandom().shuffle(shuffled)
    return "".join(shuffled)


def hash_password(plain: str) -> str:
    """Hash password with bcrypt cost factor 12."""
    return bcrypt_hash.using(rounds=BCRYPT_ROUNDS).hash(plain)


def generate_username(client_code: str) -> str:
    """Generate username from client code: lowercase, stripped."""
    return client_code.strip().lower()


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python scripts/generate_credentials.py <input.csv> <output.csv>")
        print()
        print("Input CSV must have columns: client_code, name")
        print("Optional columns: email, phone")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("JSL Client Portal — Bulk Credential Generator")
    print("=" * 60)
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print()

    rows_in = []
    with open(input_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - headers
        if missing:
            print(f"ERROR: Missing required columns: {missing}")
            print(f"Found columns: {headers}")
            sys.exit(1)
        rows_in = list(reader)

    if not rows_in:
        print("ERROR: Input file has no data rows.")
        sys.exit(1)

    print(f"Processing {len(rows_in)} clients...")
    print()

    output_rows = []
    for row in rows_in:
        code = row["client_code"].strip()
        name = row["name"].strip()
        email = row.get("email", "").strip()
        phone = row.get("phone", "").strip()

        if not code or not name:
            print(f"  SKIP: empty code or name in row: {row}")
            continue

        username = generate_username(code)
        password = generate_password()
        pw_hash = hash_password(password)

        output_rows.append({
            "client_code": code,
            "name": name,
            "email": email,
            "phone": phone,
            "username": username,
            "password": password,
            "password_hash": pw_hash,
        })

    output_fields = [
        "client_code", "name", "email", "phone",
        "username", "password", "password_hash",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=output_fields)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Generated credentials for {len(output_rows)} clients.")
    print(f"Output written to: {output_path}")
    print()
    print("-" * 60)
    print("SUMMARY")
    print("-" * 60)
    print(f"  Total input rows:    {len(rows_in)}")
    print(f"  Credentials created: {len(output_rows)}")
    print(f"  Skipped:             {len(rows_in) - len(output_rows)}")
    print(f"  Password length:     {PASSWORD_LENGTH} chars")
    print(f"  Bcrypt cost factor:  {BCRYPT_ROUNDS}")
    print("-" * 60)
    print()
    print("IMPORTANT: The output CSV contains plain-text passwords.")
    print("Share passwords with clients securely. Delete the file after import.")


if __name__ == "__main__":
    main()
