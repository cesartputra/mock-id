"""Local account password reset; no password arguments or HTTP reset endpoint."""

import argparse
import getpass
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
from app.config import DATA
from app.model.repository import Repository
from app.services.auth import AuthService


def main():
    parser = argparse.ArgumentParser(
        description="Ganti password akun lokal yang sudah ada."
    )
    parser.add_argument("--login", required=True)
    args = parser.parse_args()
    # Refuse getpass's visible-input fallback on a noninteractive terminal.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            password = getpass.getpass("Password baru (10–200 karakter): ")
            confirm = getpass.getpass("Ulangi password baru: ")
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise SystemExit(
                "Jalankan di terminal interaktif untuk memasukkan password secara tersembunyi."
            )
    if password != confirm:
        raise SystemExit("Password tidak sama. Akun belum diubah.")
    repository = Repository(DATA)
    repository.migrate()
    try:
        user = AuthService(repository).set_password(args.login, password)
    except HTTPException as error:
        raise SystemExit(error.detail) from None
    print("Password diperbarui untuk:", user["login"])
    print("Semua sesi login akun ini berakhir. Masuk kembali dengan password baru.")


if __name__ == "__main__":
    main()
