#!/usr/bin/env python3
"""
Password-hash migration script for Redline-AI.

Scans the ``users`` table and identifies rows whose ``hashed_password`` was
created with a legacy hashing scheme (passlib pbkdf2-sha256, old $2a$ bcrypt
variant, or anything that is not standard $2b$ bcrypt).

Because legacy hashes cannot be reversed, affected accounts are reset to a
random temporary password and the list of emails is printed so administrators
can notify those users.

Run inside the Docker container:

    docker compose --env-file .env.docker.local exec app \\
        python scripts/migrate-password-hashes.py

Or directly if the environment variables are already set:

    python scripts/migrate-password-hashes.py
"""

from __future__ import annotations

import os
import secrets
import string
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env.docker.local when running outside the container (best effort)
# ---------------------------------------------------------------------------

def _load_dotenv(path: str | Path) -> None:
    """Minimal .env loader -- sets os.environ for KEY=VALUE lines."""
    path = Path(path)
    if not path.is_file():
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            os.environ.setdefault(key, value)


# Try two likely locations for the env file.
_project_root = Path(__file__).resolve().parent.parent
_load_dotenv(_project_root / ".env.docker.local")
_load_dotenv(_project_root / "backend" / ".env")


# ---------------------------------------------------------------------------
# Database connection (synchronous -- simpler for a one-off migration)
# ---------------------------------------------------------------------------

import bcrypt  # same library used by app.core.security
from sqlalchemy import create_engine, text


def _build_db_url() -> str:
    user = os.environ.get("POSTGRES_USER", "redline")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    host = os.environ.get("POSTGRES_SERVER", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DB", "redline")

    if not password:
        print("ERROR: POSTGRES_PASSWORD is not set.", file=sys.stderr)
        sys.exit(1)

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


# ---------------------------------------------------------------------------
# Helpers matching app/core/security.py
# ---------------------------------------------------------------------------

STANDARD_BCRYPT_PREFIX = "$2b$"


def _is_standard_bcrypt(hashed: str) -> bool:
    """Return True if the hash is a modern $2b$ bcrypt hash."""
    return hashed.startswith(STANDARD_BCRYPT_PREFIX)


def _generate_temp_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _hash_password(plain: str) -> str:
    """Hash a password the same way as app.core.security.get_password_hash."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------

def main() -> None:
    db_url = _build_db_url()
    engine = create_engine(db_url)

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, email, hashed_password FROM users")
        ).fetchall()

    if not rows:
        print("No users found in the database.")
        return

    total = len(rows)
    ok_count = 0
    legacy_users: list[dict] = []

    for row in rows:
        user_id, email, hashed_pw = row[0], row[1], row[2]
        if _is_standard_bcrypt(hashed_pw):
            ok_count += 1
        else:
            # Determine the legacy scheme for informational purposes
            if hashed_pw.startswith("$pbkdf2-sha256$"):
                scheme = "pbkdf2-sha256 (passlib)"
            elif hashed_pw.startswith("$2a$"):
                scheme = "bcrypt $2a$ (legacy variant)"
            else:
                scheme = f"unknown (prefix: {hashed_pw[:12]}...)"

            temp_pw = _generate_temp_password()
            new_hash = _hash_password(temp_pw)

            legacy_users.append(
                {
                    "id": user_id,
                    "email": email,
                    "scheme": scheme,
                    "temp_password": temp_pw,
                    "new_hash": new_hash,
                }
            )

    # ---- Apply updates ------------------------------------------------
    if legacy_users:
        with engine.begin() as conn:
            for user in legacy_users:
                conn.execute(
                    text(
                        "UPDATE users SET hashed_password = :new_hash, "
                        "updated_at = NOW() "
                        "WHERE id = :uid"
                    ),
                    {"new_hash": user["new_hash"], "uid": user["id"]},
                )

    # ---- Report -------------------------------------------------------
    print("=" * 64)
    print("  Redline-AI  --  Password Hash Migration Report")
    print("=" * 64)
    print(f"  Total users scanned:     {total}")
    print(f"  Standard bcrypt ($2b$):  {ok_count}")
    print(f"  Legacy hashes migrated:  {len(legacy_users)}")
    print()

    if legacy_users:
        print("  The following users had legacy password hashes and have been")
        print("  reset to a temporary password.  Please notify them to change")
        print("  their password.\n")
        print(f"  {'Email':<40} {'Old Scheme':<30} {'Temp Password'}")
        print(f"  {'-'*40} {'-'*30} {'-'*20}")
        for u in legacy_users:
            print(f"  {u['email']:<40} {u['scheme']:<30} {u['temp_password']}")
        print()
    else:
        print("  All password hashes are already standard $2b$ bcrypt.")
        print("  No migration was necessary.\n")

    print("=" * 64)


if __name__ == "__main__":
    main()
