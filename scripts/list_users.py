"""Read local password-account names/roles/status without exposing credentials."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATA
from app.model.database import Database
from app.services.auth import list_accounts
from app.services.secrets_store import SecretBox


def display_accounts(con, role):
    # Do not let listing create a replacement encryption key for existing data.
    if not os.getenv("MOCK_ID_ENCRYPTION_KEY") and not (DATA / ".local.key").is_file():
        raise SystemExit(
            "Kunci data tidak tersedia. Gunakan folder/config data yang sama dengan server."
        )
    try:
        rows = list_accounts(con, SecretBox(DATA), role)
    except Exception as error:
        raise SystemExit(
            "Daftar akun tidak dapat dibaca. Periksa database dan kunci enkripsi server."
        ) from error
    if not rows:
        print("Belum ada akun password" + (f" dengan peran {role}." if role else "."))
        return
    # JSON-quoted names keep terminal control characters from being interpreted.
    names = [json.dumps(row["login"], ensure_ascii=False) for row in rows]
    width = max(len("USERNAME"), *(len(name) for name in names))
    print(f'{"USERNAME":<{width}}  {"PERAN":<12}  STATUS')
    for name, row in zip(names, rows):
        print(
            f'{name:<{width}}  {row["role"]:<12}  {"Aktif" if row["enabled"] else "Nonaktif"}'
        )
    print(
        f"\nTotal: {len(rows)} akun password. Sesi pemohon tanpa login tidak termasuk."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Daftar akun lokal, tanpa password atau hash."
    )
    parser.add_argument(
        "--role", choices=["admin", "helpdesk", "integration", "applicant"]
    )
    args = parser.parse_args()
    path = DATA / "workspace.sqlite3"
    if os.getenv("MOCK_ID_DATABASE_URL"):
        # Deployment adapter, when explicitly configured; SELECT-only transaction.
        with Database(path).connect() as con:
            con.execute("SET TRANSACTION READ ONLY")
            display_accounts(con, args.role)
    elif not path.is_file():
        print(
            "Belum ada database akun. Jalankan user:create untuk membuat akun pertama."
        )
    else:
        # Listing never initializes schema, changes journal mode or creates files.
        con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            if not con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='principals'"
            ).fetchone():
                print(
                    "Belum ada akun password. Jalankan user:create untuk membuat akun pertama."
                )
            else:
                display_accounts(con, args.role)
        finally:
            con.close()


if __name__ == "__main__":
    main()
