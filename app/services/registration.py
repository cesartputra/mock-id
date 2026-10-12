"""Local registration adapter: illustrates the host app handoff, never OJK."""
import secrets
from fastapi import HTTPException
from app.model.repository import utcnow


class RegistrationService:
    def __init__(self, sessions, repository):
        self.sessions = sessions
        self.repository = repository

    def submit(self, body):
        verification = None
        # Serialize with reset: an earlier successful result cannot authorize
        # the post-KYC handoff after capture generation changes.
        with self.sessions.lock:
            if body.debtor_type == 'individual' and not body.preview:
                if not body.session_id or not body.verification_id:
                    raise HTTPException(422, 'Selesaikan KYC dan liveness terlebih dahulu.')
                session = self.sessions.get(body.session_id)
                verification = session.last_result
                if (not session.consumed or session.processing or not verification
                        or verification['id'] != body.verification_id or verification['status'] != 'pass'):
                    raise HTTPException(409, 'Hasil KYC belum lolos atau capture sudah diambil ulang.')
                existing = self.repository.registration_for_verification(body.verification_id)
                if existing:
                    return existing
            elif body.verification_id or body.session_id:
                raise HTTPException(422, 'Pratinjau dan jalur non-perseorangan tidak menerima bukti KYC.')
            record = {'id': 'DEMO-'+secrets.token_hex(5).upper(), 'created': utcnow(),
                      'debtor_type': body.debtor_type, 'name': body.name.strip(),
                      'email': body.email, 'phone': body.phone, 'address': body.address.strip(),
                      'purpose': body.purpose, 'status': 'received_mock',
                      'mode': 'preview' if body.preview else 'mock',
                      'verification_id': verification['id'] if verification else None,
                      'kyc': 'local_checks_passed' if verification else 'preview' if body.preview else 'not_applicable',
                      'identity_verified': False, 'submitted_to_ojk': False}
            self.repository.save_registration(record)
        self.repository.audit('Pendaftaran demo lokal', f'Jenis {body.debtor_type}; mode {record["mode"]}; tidak dikirim ke OJK.', record['id'])
        return record
