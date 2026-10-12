import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import DATA
from app.model.repository import Repository
from app.services.secrets_store import SecretBox
from app.services.evidence import EvidenceStore, S3PrivateStorage
import os

repository = Repository(DATA)
repository.migrate()
storage = (
    S3PrivateStorage(
        os.environ["MOCK_ID_EVIDENCE_BUCKET"], os.getenv("MOCK_ID_S3_ENDPOINT")
    )
    if os.getenv("MOCK_ID_EVIDENCE_BUCKET")
    else None
)
print(
    "Bukti dihapus karena retensi:",
    EvidenceStore(repository, SecretBox(DATA), storage).purge(),
)
