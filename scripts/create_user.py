"""Create a local operator/service account without committed default passwords."""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATA
from app.model.repository import Repository
from app.services.auth import AuthService

parser = argparse.ArgumentParser()
parser.add_argument("--login", required=True)
parser.add_argument(
    "--role", choices=["applicant", "helpdesk", "admin", "integration"], required=True
)
args = parser.parse_args()
password = getpass.getpass("Password (minimal 10 karakter): ")
if password != getpass.getpass("Ulangi password: "):
    raise SystemExit("Password tidak sama.")
repository = Repository(DATA)
repository.migrate()
user = AuthService(repository).create_user(args.login, password, args.role)
repository.audit(
    "Akun dibuat melalui administrator lokal",
    "Role " + args.role + "; actor " + user["id"],
)
print("Akun dibuat:", user["login"], "role", user["role"])
