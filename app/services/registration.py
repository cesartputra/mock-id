"""Local registration adapter: illustrates the host app handoff, never OJK."""
import secrets
from fastapi import HTTPException
from app.model.repository import utcnow


class RegistrationService:
    def __init__(self, sessions, repository, workflow=None, actor=None):
        self.sessions = sessions
        self.repository = repository
        self.workflow, self.actor = workflow, actor

    def submit(self, body):
        if self.workflow and self.workflow.policy.mode!='demo':raise HTTPException(503,'Formulir pendaftaran ini hanya adapter demo. Gunakan integrasi aplikasi induk berwenang untuk produksi.')
        verification = None
        # Serialize with reset: an earlier successful result cannot authorize
        # the post-KYC handoff after capture generation changes.
        with self.sessions.lock, self.repository.connect(write=True):
            if body.debtor_type == 'individual' and not body.preview:
                if not body.verification_id:
                    raise HTTPException(422, 'Selesaikan KYC dan liveness terlebih dahulu.')
                if not self.workflow or not self.actor:
                    raise HTTPException(409, 'Handoff membutuhkan keputusan permohonan persisten.')
                with self.repository.connect() as con:
                    application_id = body.application_id
                    if not application_id:
                        rows=con.execute('SELECT id FROM applications WHERE owner_id=?',(self.actor['id'],)).fetchall()
                        application_id=next((r['id'] for r in rows if self.workflow.get(con,r['id'])['payload'].get('verification_id')==body.verification_id),None)
                    if not application_id: raise HTTPException(409, 'Keputusan permohonan belum tersedia.')
                    application=self.workflow.get(con,application_id)
                    self.workflow.authorize(con,application,self.actor)
                    if application['state'] not in ['AUTO_APPROVED','MANUAL_APPROVED','SLIK_PENDING','SLIK_READY'] or application['payload'].get('verification_id')!=body.verification_id:
                        raise HTTPException(409, 'Keputusan belum lolos atau bukti sudah diganti.')
                    decision=application['payload'].get('decision')
                    import time
                    if not decision or decision['revision']!=application['revision'] or decision['expires']<=time.time():raise HTTPException(409,'Keputusan kedaluwarsa atau dibatalkan.')
                    identity=self.workflow.identity(con,application)
                    if body.name.strip().casefold()!=identity['name'].strip().casefold():raise HTTPException(409,'Nama pendaftaran harus sesuai identitas yang diputuskan server.')
                    verification={'id':body.verification_id,'name':identity['name']}
                existing = self.repository.registration_for_verification(body.verification_id)
                if existing:
                    if existing.get('owner_id')!=self.actor['id']:raise HTTPException(404,'Pendaftaran tidak ditemukan.')
                    return existing
            elif body.verification_id or body.session_id or body.application_id:
                raise HTTPException(422, 'Pratinjau dan jalur non-perseorangan tidak menerima bukti KYC.')
            record = {'id': 'DEMO-'+secrets.token_hex(5).upper(), 'created': utcnow(),
                      'owner_id': self.actor['id'] if self.actor else None, 'application_id': application['id'] if verification else None,
                      'debtor_type': body.debtor_type, 'name': verification['name'] if verification else body.name.strip(),
                      'email': body.email, 'phone': body.phone, 'address': body.address.strip(),
                      'purpose': body.purpose, 'status': 'received_mock',
                      'mode': 'preview' if body.preview else 'mock',
                      'verification_id': verification['id'] if verification else None,
                      'kyc': 'local_checks_passed' if verification else 'preview' if body.preview else 'not_applicable',
                      'identity_verified': False, 'submitted_to_ojk': False}
            self.repository.save_registration(record)
        self.repository.audit('Pendaftaran demo lokal', f'Jenis {body.debtor_type}; mode {record["mode"]}; tidak dikirim ke OJK.', record['id'])
        return record
