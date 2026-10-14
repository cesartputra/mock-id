import hashlib
import asyncio
import json
import time
import secrets
import math
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, ConfigDict, field_validator
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import MAX_IMAGE_BYTES, MAX_FRAME_BYTES, MAX_FRAMES, MAX_ATTEMPTS
from app.model.repository import utcnow
from app.services.imaging import CaptureError, decode_image
from app.services.pipeline import ModelUnavailable
from app.services.liveness import LiveCapture
from app.services.document_consensus import DocumentConsensus
from app.services.auth import actor
from app.services.workflow import TRANSITIONS
from app.services.verification_entry import CONSENT_VERSION

router = APIRouter(prefix='/api', dependencies=[Security(APIKeyHeader(name='X-Local-Client', auto_error=False))])


def services(request):
    return request.app.state.sessions, request.app.state.verifier, request.app.state.repository


async def image_upload(upload, limit=MAX_IMAGE_BYTES):
    content = await upload.read(limit+1)
    await upload.close()
    if len(content) > limit:
        raise HTTPException(413, f'Gambar melebihi batas {limit // 1024} KB.')
    try:
        return decode_image(content), hashlib.sha256(content).hexdigest()
    except CaptureError as exc:
        raise HTTPException(422, str(exc)) from exc


def frame_manifest(raw, count, expected):
    try:
        metadata=json.loads(raw)
    except (json.JSONDecodeError,TypeError) as exc:
        raise HTTPException(422,'Manifest frame tidak valid.') from exc
    if not isinstance(metadata,list) or not 24<=count<=MAX_FRAMES or count!=len(metadata):
        raise HTTPException(422,'Butuh 24–48 frame liveness dengan manifest yang sesuai.')
    times,groups=[],[]
    for item in metadata:
        if not isinstance(item,dict) or item.get('challenge') not in expected or type(item.get('t_ms')) not in [int,float] or not math.isfinite(item['t_ms']):
            raise HTTPException(422,'Metadata tantangan tidak valid.')
        times.append(item['t_ms'])
        if not groups or groups[-1]!=item['challenge']:
            groups.append(item['challenge'])
    if groups!=expected or any(sum(m['challenge']==c for m in metadata)<8 for c in expected):
        raise HTTPException(422,'Urutan tantangan tidak sesuai instruksi server.')
    if times[0]<0 or times[-1]>60_000 or any(not 90<=b-a<=1500 for a,b in zip(times,times[1:])):
        raise HTTPException(422,'Timestamp frame tidak valid. Ulangi rekaman langsung.')
    return metadata


def manifest_digest(metadata):
    return hashlib.sha256(json.dumps(metadata,sort_keys=True,separators=(',',':')).encode()).hexdigest()


async def frame_uploads(frames):
    images,hashes=[],[]
    for file in frames:
        decoded,digest=await image_upload(file,MAX_FRAME_BYTES)
        images.append(decoded);hashes.append(digest)
    if len(set(hashes))<len(hashes)*.8:
        raise HTTPException(422,'Terlalu banyak frame identik. Gunakan rekaman gerakan kamera, bukan pengulangan foto.')
    return images,hashes


@router.post('/sessions/{session_id}/liveness/start')
def start_liveness(session_id: str, request: Request):
    sessions,_,repository=services(request)
    with sessions.lock:
        session=sessions.get(session_id)
        sessions.check_revision(session, request)
        if session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409,'Sesi sedang atau sudah diproses.')
        if session.document is None:
            raise HTTPException(422,'Baca KTP sebelum merekam liveness.')
        session.liveness_attempts+=1
        session.liveness_nonce=secrets.token_urlsafe(32)
        session.liveness_started=time.monotonic()
        token = session.liveness_nonce
        started = session.liveness_started
        sessions.clear_liveness(session)
        session.liveness_nonce = token
        session.liveness_started = started
        session.stream_state = LiveCapture(session.challenges)
        result={**session.public(),'capture_nonce':session.liveness_nonce,'liveness_attempts':session.liveness_attempts, 'turn_direction': session.stream_state.gestures.turn_direction}
    repository.audit('Rekaman liveness dimulai',f'Percobaan rekaman {session.liveness_attempts}; tantangan server.',session.id)
    return result


@router.post('/sessions/{session_id}/liveness/frame')
async def live_frame(session_id: str, request: Request, capture_nonce: str = Form(...),
                     seq: int = Form(ge=0), image: UploadFile = File(...)):
    sessions, verifier, repository = services(request)
    with sessions.lock:
        session = sessions.get(session_id)
        sessions.check_revision(session, request)
        if (not session.liveness_nonce or not secrets.compare_digest(session.liveness_nonce, capture_nonce)
                or session.consumed or session.processing or session.liveness_processing):
            raise HTTPException(409, 'Token rekaman tidak valid atau pemeriksaan frame masih berjalan.')
        capture = session.stream_state
        revision = session.revision
        session.liveness_processing = True
    try:
        decoded, digest = await image_upload(image, MAX_FRAME_BYTES)
        problem = capture.accept(digest, seq, time.monotonic())
        if problem:
            raise HTTPException(422, problem)
        try:
            result = await request.app.state.inference_queue.run(verifier.inspect_liveness_frame, capture, decoded, digest, seq, session=session, flag="liveness_processing")
        except CaptureError as exc:
            capture.pause_detection()
            result = capture.result({'ready': False, 'warnings': [{'code': 'face_missing', 'message': str(exc)}], 'face_box': None})
        except ModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        with sessions.lock:
            sessions.check_revision(session,request)
            if session.revision != revision:
                raise HTTPException(409, 'Capture sudah diambil ulang.')
            if result['done']:
                session.liveness_nonce = None
                session.liveness_result = result
                # This proof is generated only after actual sequential inference.
                if result['passed']:
                    session.evidence_frames = capture.evidence_images.copy()
                    session.liveness_selfie = capture.selfie_hash
                    session.liveness_proof = secrets.token_urlsafe(32)
                    result = {**result, 'proof_token': session.liveness_proof}
                session.stream_state = None
                repository.audit('Liveness real time diperiksa', result['reason'], session.id)
            result['image_size'] = [decoded.shape[1], decoded.shape[0]]
            return live_result(result,actor(request))
    finally:
        with sessions.lock:
            if not request.app.state.inference_queue.pending(session.id): session.liveness_processing = False


@router.post('/sessions/{session_id}/liveness/check')
async def check_liveness(session_id: str, request: Request, capture_nonce: str = Form(...),
                         manifest: str = Form(...), selfie: UploadFile = File(...), frames: list[UploadFile] = File(...)):
    sessions,verifier,repository=services(request)
    session=sessions.get(session_id)
    sessions.check_revision(session, request)
    revision = session.revision
    metadata=frame_manifest(manifest,len(frames),session.challenges)
    selfie_image,selfie_hash=await image_upload(selfie)
    decoded,hashes=await frame_uploads(frames)
    span=(metadata[-1]['t_ms']-metadata[0]['t_ms'])/1000
    with sessions.lock:
        session=sessions.get(session_id)
        sessions.check_revision(session, request)
        if session.revision != revision or (session.stream_state and session.stream_state.sequence):
            raise HTTPException(409, 'Capture berubah atau streaming sudah dimulai.')
        if not session.liveness_nonce or not secrets.compare_digest(session.liveness_nonce,capture_nonce) or session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409,'Token rekaman tidak valid atau sudah digunakan. Rekam ulang tantangan baru.')
        elapsed=time.monotonic()-session.liveness_started
        if span<7 or elapsed<span-.75 or elapsed>90:
            raise HTTPException(422,'Rekaman tidak sesuai durasi sesi kamera. Rekam ulang secara langsung.')
        session.liveness_nonce=None
        session.liveness_processing=True
    try:
        try:
            result=await request.app.state.inference_queue.run(verifier.evaluate_liveness,session,selfie_image,decoded,metadata, session=session, flag="liveness_processing")
        except CaptureError as exc:
            result={'passed':False,'reason':str(exc),'mode':'real'}
        except ModelUnavailable as exc:
            raise HTTPException(503,str(exc)) from exc
        session.stream_state = None
        session.liveness_result=result
        if result['passed']:
            session.liveness_hashes=hashes
            session.liveness_manifest=manifest_digest(metadata)
            session.liveness_selfie=selfie_hash
        repository.audit('Liveness diperiksa','Terpenuhi' if result['passed'] else result['reason'],session.id)
        return live_result(result,actor(request))
    finally:
        with sessions.lock:
            if not request.app.state.inference_queue.pending(session.id): session.liveness_processing=False


@router.get('/health')
def health(request: Request):
    _, verifier, _ = services(request)
    return verifier.availability()


@router.get('/workspace')
def workspace(request: Request):
    _, verifier, repository = services(request)
    records = repository.results()
    if actor(request)['role']=='helpdesk':
        with repository.connect() as con:
            cases = con.execute("SELECT application_id FROM manual_cases WHERE state!='CANCELLED' AND (assigned_to IS NULL OR assigned_to=?)",(actor(request)['id'],)).fetchall()
            allowed = {request.app.state.workflow.get(con,row['application_id'])['payload'].get('verification_id') for row in cases}
        records = [r for r in records if r['id'] in allowed]
    policy=request.app.state.workflow.policy
    return {'routing_policy': {'automatic_threshold': policy.automatic_threshold, 'mode': policy.mode, 'calibrated':policy.calibrator.calibrated, 'version': policy.calibrator.version}, 'records': records, 'audit': repository.events() if actor(request)['role']=='admin' else [], 'settings': repository.settings(), 'health': verifier.availability()}


class CaptureStart(BaseModel):
    application_id: str | None = None
    consent: bool = Field(default=False, strict=True)
    captcha_token: str | None = Field(default=None, min_length=20, max_length=100)


@router.post('/sessions')
def create_session(request: Request, body: CaptureStart | None = None):
    sessions, _, repository = services(request)
    # The optional persistent application is resumed only by its owner. Each
    # new camera session invalidates the preceding evidence generation.
    who = actor(request)
    # Public applicants must complete preflight. Authenticated administrators
    # retain their existing internal API path; the browser UI gates both roles.
    gated = who['role'] == 'applicant' or bool(body and (body.consent or body.captcha_token))
    if gated:
        if not body or not body.consent:
            raise HTTPException(403, 'Setujui pemrosesan capture sebelum verifikasi.')
        if not body.captcha_token:
            raise HTTPException(403, 'Selesaikan CAPTCHA sebelum melanjutkan verifikasi.')
        request.app.state.verification_entry.consume(who['id'], body.captcha_token)
    request.app.state.auth.limit('session-start:'+who['id'],12,3600)
    if body and body.application_id:
        snapshot = request.app.state.workflow.snapshot(body.application_id, who)
        app = request.app.state.workflow.invalidate(body.application_id, who, snapshot['capture_revision']+1,new_capture=True)
    else:
        app = request.app.state.workflow.create(who)
    if gated:
        request.app.state.workflow.attest(app['id'], who, True)
        repository.audit('Persetujuan capture dan CAPTCHA', CONSENT_VERSION, app['id'])
    session = sessions.create(who['id'], app['id'], app['revision'])
    request.app.state.workflow.link_session(session)
    repository.audit('Sesi dibuat', 'Capture OCR, liveness, dan KYC lokal.', session.id)
    return session.public()


@router.post('/sessions/{session_id}/retry')
def retry_session(session_id: str, request: Request):
    sessions, _, repository = services(request)
    with sessions.lock, repository.connect(write=True):
        session = sessions.get(session_id)
        sessions.check_revision(session, request)
        plan = sessions.retry_plan(session)
        previous = vars(session).copy()
        try:
            session = sessions.retry(session_id)
            repository.audit('Percobaan ulang', f'Percobaan {session.attempt}; nonce server diperbarui.', session.id)
            if session.application_id: request.app.state.workflow.invalidate(session.application_id, actor(request), session.revision)
        except Exception:
            # A failed audit must not strand the client with an old nonce or
            # clear its retry evidence before the new nonce can be returned.
            vars(session).update(previous)
            raise
    return {**session.public(), 'retry': plan}


class Retake(BaseModel):
    stage: str = Field(pattern='^(document|liveness|holding)$')
    nonce: str = Field(min_length=20, max_length=100)


@router.post('/sessions/{session_id}/retake')
def retake(session_id: str, body: Retake, request: Request):
    sessions, _, repository = services(request)
    with sessions.lock, repository.connect(write=True):
        session = sessions.get(session_id)
        sessions.check_revision(session, request)
        previous = vars(session).copy()
        try:
            session = sessions.reset(session_id, body.stage, body.nonce)
            repository.audit('Capture diambil ulang', f'Tahap {body.stage}; generasi {session.revision}; nonce diperbarui.', session.id)
            if session.application_id: request.app.state.workflow.invalidate(session.application_id, actor(request), session.revision)
        except Exception:
            vars(session).update(previous)
            raise
    return session.public()


@router.post('/sessions/{session_id}/document')
async def document(session_id: str, request: Request, image: UploadFile = File(...), capture_token: str | None = Form(None)):
    sessions, verifier, repository = services(request)
    session = sessions.get(session_id)
    sessions.check_revision(session, request)
    revision = session.revision
    nonce = session.nonce
    live_token = session.liveness_nonce
    if session.consumed or session.processing or session.liveness_processing:
        raise HTTPException(409, 'Sesi sudah diproses. Gunakan retry atau sesi baru.')
    decoded, digest = await image_upload(image)
    with sessions.lock:
        sessions.check_revision(session, request)
        if session.revision != revision or session.processing or session.consumed:
            raise HTTPException(409,'Capture berubah. Gunakan frame terbaru.')
        result = None
        if capture_token:
            probe=session.document_probe
            if not probe or probe['revision']!=revision or probe['digest']!=digest or time.monotonic()-probe['created']>20 or not secrets.compare_digest(probe['token'],capture_token):
                raise HTTPException(409,'Bukti OCR otomatis berubah atau kedaluwarsa. Buka kamera kembali.')
            result=deepcopy(probe['reading'])
            session.document_probe=None  # Reserve this one-use proof under the session lock.
        if session.document_attempts>=MAX_ATTEMPTS: raise HTTPException(429,'Batas tiga pengambilan OCR tercapai. Buat permohonan baru.')
        session.document_attempts+=1
    try:
        if result is None:
            result = await request.app.state.inference_queue.run(verifier.document, decoded)
    except CaptureError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    with sessions.lock:
        sessions.get(session_id)
        sessions.check_revision(session, request)
        if session.revision != revision or session.nonce != nonce or session.liveness_nonce != live_token or session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409, 'Capture berubah atau sesi sedang diproses.')
        session.document_digest = digest
        session.document = decoded
        session.document_result = result
        session.document_probe = None
        session.document_consensus = None
        # Live-person evidence is independent of the card image. Replacing the
        # document still forces fresh face/NIK comparisons in final verify.
        if not (session.liveness_result and session.liveness_result.get('passed')):
            sessions.clear_liveness(session)
    repository.audit('OCR selesai', f'NIK terbaca; confidence {result["confidence"]:.3f}. Gambar tidak disimpan ke disk.', session.id)
    return result if actor(request)['role'] in ['admin','helpdesk'] else {k:v for k,v in result.items() if k not in ['confidence','quality','boxes','scores','field_meta','text_quality']}


@router.post('/sessions/{session_id}/auto-capture/check')
async def auto_capture_check(session_id: str, request: Request, image: UploadFile = File(...), context: str = Form(...)):
    sessions, verifier, _ = services(request)
    if context not in ['document', 'holding']:
        raise HTTPException(422, 'Jenis pengambilan otomatis tidak valid.')
    with sessions.lock:
        session = sessions.get(session_id)
        sessions.check_revision(session, request)
        revision = session.revision
        if session.processing or session.consumed or session.liveness_processing:
            raise HTTPException(409, 'Pemeriksaan lain masih berjalan atau sesi sudah diproses.')
        if context == 'holding' and (session.document_result is None or not session.liveness_result or not session.liveness_result.get('passed')):
            raise HTTPException(422, 'Selesaikan OCR dan liveness sebelum foto bersama KTP.')
        now = time.monotonic()
        if now-session.last_preview < .5:
            raise HTTPException(429, 'Tunggu hasil pemeriksaan kamera sebelumnya.')
        session.last_preview = now
        document = session.document
        identity = dict(session.document_result['fields']) if session.document_result else None
    decoded, digest = await image_upload(image)
    try:
        result = await request.app.state.inference_queue.run(verifier.inspect_auto_capture, decoded, context, document, identity)
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    with sessions.lock:
        sessions.get(session_id)
        sessions.check_revision(session,request)
        if session.revision != revision or session.processing or session.consumed:
            raise HTTPException(409, 'Capture sudah berubah. Gunakan pengambilan terbaru.')
        if context == 'document':
            reading=result.pop('_document_reading',None)
            session.document_probe=None
            if result['ready'] and reading:
                session.document_consensus=session.document_consensus or DocumentConsensus()
                merged,pending,count=session.document_consensus.observe(reading,digest,time.monotonic())
                result.update(complete=merged is not None,ready=merged is not None,
                              identity_ready=merged is not None,verified_frames=count,
                              card_box=reading.get('card_box'),field_feedback=reading.get('field_feedback',{}))
                if merged:
                    token=secrets.token_urlsafe(32)
                    session.document_probe={'token':token,'digest':digest,'revision':revision,'created':time.monotonic(),'reading':merged}
                    result.update(document_capture_token=token,field_feedback=merged['field_feedback'],warnings=[])
                else:
                    labels={'nik':'NIK','name':'nama','birth':'tanggal lahir'}
                    result['warnings']=[{'code':'ocr_stabilizing','message':'Memastikan '+', '.join(labels[key] for key in pending)+' dari beberapa frame. Tahan kartu pada jarak yang tetap fokus.'}]
            elif session.document_consensus:
                # Invalid/occluded observations must not preserve a ready token.
                session.document_consensus=None
    return capture_result({**result, 'image_size': [decoded.shape[1], decoded.shape[0]]},actor(request))


@router.post('/sessions/{session_id}/capture-check')
async def capture_check(session_id: str, request: Request, image: UploadFile = File(...), context: str = Form('selfie')):
    sessions, verifier, _ = services(request)
    if context not in ['selfie','holding']:
        raise HTTPException(422,'Jenis capture tidak valid.')
    with sessions.lock:
        session=sessions.get(session_id)
        sessions.check_revision(session, request)
        revision = session.revision
        if session.processing or session.consumed or session.liveness_processing:
            raise HTTPException(409,'Sesi sudah diproses. Buat sesi baru atau retry.')
        now=time.monotonic()
        if now-session.last_preview<.5:
            raise HTTPException(429,'Pemeriksaan kamera terlalu cepat.')
        session.last_preview=now
    decoded,_=await image_upload(image,MAX_FRAME_BYTES)
    try:
        result = await request.app.state.inference_queue.run(verifier.inspect_capture, decoded, context=='holding')
        result['image_size'] = [decoded.shape[1], decoded.shape[0]]
        with sessions.lock:
            sessions.check_revision(session,request)
            if session.revision != revision:
                raise HTTPException(409, 'Capture sudah diambil ulang.')
        return capture_result(result,actor(request))
    except ModelUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc


class IdentityCorrection(BaseModel):
    model_config=ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)
    birth: str = Field(default='', max_length=10)
    address: str = Field(default='', max_length=200)
    @field_validator('birth')
    @classmethod
    def valid_birth(cls,value):
        if value:
            from datetime import date
            parsed=date.fromisoformat(value)
            if parsed>date.today():raise ValueError('Tanggal lahir tidak boleh mendatang.')
        return value


@router.patch('/sessions/{session_id}/identity')
def identity(session_id: str, body: IdentityCorrection, request: Request):
    sessions, _, _ = services(request)
    with sessions.lock:
        session = sessions.get(session_id)
        sessions.check_revision(session, request)
        if session.processing or session.liveness_processing or session.consumed or not session.document_result:
            raise HTTPException(409, 'OCR belum selesai atau sesi sudah diproses.')
        session.document_result['fields'].update(body.model_dump())
    return session.document_result['fields']


@router.post('/sessions/{session_id}/verify')
async def verify(session_id: str, request: Request, nonce: str = Form(...),
                 selfie: UploadFile = File(...), holding: UploadFile = File(...),
                 manifest: str = Form('[]'), frames: list[UploadFile] = File(default=[]),
                 proof_token: str = Form('')):
    sessions, verifier, repository = services(request)
    session = sessions.get(session_id)
    sessions.check_revision(session, request)
    revision = session.revision
    # Legacy batch recordings remain readable; streaming proof has no upload of
    # a client-authored challenge manifest or unverified replacement frames.
    metadata, decoded_frames, hashes = [], [], []
    if not proof_token:
        metadata = frame_manifest(manifest, len(frames), session.challenges)
        decoded_frames, hashes = await frame_uploads(frames)
    elif frames or manifest != '[]':
        raise HTTPException(422, 'Bukti streaming tidak menerima frame pengganti.')
    face_image, selfie_hash = await image_upload(selfie)
    holding_image, holding_digest = await image_upload(holding)
    with sessions.lock:
        sessions.check_revision(session, request)
        if session.revision != revision:
            raise HTTPException(409, 'Capture sudah diambil ulang.')
        if not session.liveness_result or not session.liveness_result.get('passed'):
            raise HTTPException(422, 'Liveness belum lolos pemeriksaan model. Rekam ulang sebelum melanjutkan.')
        if proof_token:
            bound = session.liveness_proof and secrets.compare_digest(session.liveness_proof, proof_token) and session.liveness_result.get('stream')
        else:
            bound = hashes == session.liveness_hashes and manifest_digest(metadata) == session.liveness_manifest and not session.liveness_result.get('stream')
        if not bound or selfie_hash != session.liveness_selfie:
            raise HTTPException(409, 'Capture berbeda dari rekaman yang diperiksa. Rekam ulang liveness.')
        session = sessions.consume(session_id, nonce)
        session.proof_checked_revision = revision
        session.holding_digest = holding_digest
    try:
        repository.audit('Verifikasi dimulai', f'Percobaan {session.attempt}; nonce dikonsumsi.', session.id)
        result = await request.app.state.inference_queue.run(verifier.run, session, face_image, holding_image, decoded_frames, metadata, session=session, flag="processing")
        application = request.app.state.workflow.ingest(session, result, face_image, holding_image,
            session.evidence_frames or [next(f for f,m in zip(decoded_frames,metadata) if m['challenge']==c) for c in session.challenges] if decoded_frames else session.evidence_frames)
        if application:
            if application['state']=='MANUAL_PENDING':
                application=await asyncio.to_thread(request.app.state.manual.admit_today,application['id'],actor(request))
            if application['state']=='AUTO_APPROVED':
                application=await asyncio.to_thread(request.app.state.slik.issue,application['id'],actor(request))
            result['application'] = application
            normalized = {'AUTO_APPROVED':'pass','SLIK_PENDING':'pass','SLIK_READY':'pass','CAPTURE_RETRY':'capture','TECHNICAL_PENDING':'technical','MANUAL_PENDING':'manual','MANUAL_SCHEDULED':'manual','REJECTED':'attack' if application['routing']['security_review'] else 'rejected'}.get(application['state'])
            if normalized:
                result['model_status'] = result['status']
                result['model_reason'] = result['reason']
                result['status'] = normalized
                result['reason'] = application['reason']
            if application.get('retry'):result['retry'] = application['retry']
            repository.save_result(result)
        session.last_result = result
        return applicant_result(result, actor(request))
    except Exception:
        error_id = uuid.uuid4().hex[:12]
        logging.getLogger(__name__).error('Verification failure %s for session %s', error_id, session.id)
        reason = 'Pemeriksaan belum dapat diselesaikan atau disimpan. Coba jalankan model kembali; capture yang sudah lolos dipertahankan.'
        retry = {'stage': 'verify', 'label': 'Jalankan pemeriksaan ulang', 'reason': reason}
        # The nonce stays consumed. A bounded /retry rotates it while retaining
        # the document and validated liveness proof, even if persistence failed.
        with sessions.lock:
            session.last_result = {'status': 'technical', 'reason': reason, 'retry': retry}
        try: request.app.state.workflow.technical(session)
        except Exception: pass
        return JSONResponse({'detail': reason, 'code': 'verification_unavailable',
                             'request_id': error_id, 'retry': retry}, status_code=503)
    finally:
        with sessions.lock:
            if not request.app.state.inference_queue.pending(session.id): session.processing = False


class Rules(BaseModel):
    face_cosine: float = Field(ge=.1, le=.9)
    pad_probability: float = Field(ge=.5, le=.99)
    deepfake_risk: float = Field(ge=.01, le=.99)
    blur_min: float = Field(ge=10, le=300)


@router.put('/settings')
def settings(body: Rules, request: Request):
    _, _, repository = services(request)
    repository.set_settings(body.model_dump())
    return repository.settings()


class Review(BaseModel):
    decision: str = Field(pattern='^(approved|rejected)$')
    note: str = Field(min_length=5, max_length=250)


@router.post('/records/{result_id}/review')
def review(result_id: str, body: Review, request: Request):
    raise HTTPException(409, 'Gunakan /applications/{id}/manual/review dengan kasus dan versi bukti yang diperiksa.')



class Reservation(BaseModel):
    at: str


@router.post('/records/{result_id}/schedule')
def schedule(result_id: str, body: Reservation, request: Request):
    raise HTTPException(409, 'Gunakan reservasi /applications/{id}/manual/reserve dengan kapasitas atomik.')


def applicant_result(result, who):
    if who['role'] in ['admin','helpdesk']: return result
    value = {k:v for k,v in result.items() if k not in ['scores','rules','checks','dukcapil']}
    value['checks'] = [{k:c[k] for k in ['name','status','mode','stage'] if k in c} for c in result.get('checks',[]) if c.get('effect') != 'advisory']
    value['scores'] = {}
    return value


def capture_result(result, who):
    if who['role'] in ['admin','helpdesk']: return result
    keys=['ready','complete','context','warnings','face_box','card_box','image_size','nik_readable','nik_matches','hand_detected','subject_key','mode','pad_review_required','identity_ready','verified_frames','document_capture_token','field_feedback']
    return {k:result[k] for k in keys if k in result}


def live_result(result, who):
    if who['role'] in ['admin','helpdesk']: return result
    keys=['passed','done','phase','challenge','turn_direction','neutral_samples','blink_closed','frames','selfie_seq','reason','proof_token','stream','mode','image_size','pad_passed','pad_review_required']
    value={k:result[k] for k in keys if k in result}
    value['completed']=[{k:item[k] for k in ['challenge','passed'] if k in item} for item in result.get('completed',[])]
    if 'feedback' in result:value['feedback']=capture_result(result['feedback'],who)
    return value
