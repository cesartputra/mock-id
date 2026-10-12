import hashlib
import json
import time
import secrets
import math
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.config import MAX_IMAGE_BYTES, MAX_FRAME_BYTES, MAX_FRAMES, MAX_ATTEMPTS
from app.model.repository import utcnow
from app.services.imaging import CaptureError, decode_image
from app.services.pipeline import ModelUnavailable
from app.services.liveness import LiveCapture

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
        if session.liveness_attempts>=MAX_ATTEMPTS:
            raise HTTPException(429,'Batas tiga rekaman liveness tercapai. Mulai sesi baru.')
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
            result = await run_in_threadpool(verifier.inspect_liveness_frame, capture, decoded, digest, seq)
        except CaptureError as exc:
            capture.gestures.reset_action()
            result = capture.result({'ready': False, 'warnings': [{'code': 'face_missing', 'message': str(exc)}], 'face_box': None})
        except ModelUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        with sessions.lock:
            if session.revision != revision:
                raise HTTPException(409, 'Capture sudah diambil ulang.')
            if result['done']:
                session.liveness_nonce = None
                session.liveness_result = result
                # This proof is generated only after actual sequential inference.
                if result['passed']:
                    session.liveness_selfie = capture.selfie_hash
                    session.liveness_proof = secrets.token_urlsafe(32)
                    result = {**result, 'proof_token': session.liveness_proof}
                session.stream_state = None
                repository.audit('Liveness real time diperiksa', result['reason'], session.id)
            result['image_size'] = [decoded.shape[1], decoded.shape[0]]
            return result
    finally:
        with sessions.lock:
            session.liveness_processing = False


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
            result=await run_in_threadpool(verifier.evaluate_liveness,session,selfie_image,decoded,metadata)
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
        return result
    finally:
        with sessions.lock:
            session.liveness_processing=False


@router.get('/health')
def health(request: Request):
    _, verifier, _ = services(request)
    return verifier.availability()


@router.get('/workspace')
def workspace(request: Request):
    _, verifier, repository = services(request)
    return {'records': repository.results(), 'audit': repository.events(), 'settings': repository.settings(), 'health': verifier.availability()}


@router.post('/sessions')
def create_session(request: Request):
    sessions, _, repository = services(request)
    session = sessions.create()
    repository.audit('Sesi dibuat', 'Capture OCR, liveness, dan KYC lokal.', session.id)
    return session.public()


@router.post('/sessions/{session_id}/retry')
def retry_session(session_id: str, request: Request):
    sessions, _, repository = services(request)
    with sessions.lock:
        sessions.check_revision(sessions.get(session_id), request)
        plan = sessions.retry_plan(sessions.get(session_id))
        session = sessions.retry(session_id)
    repository.audit('Percobaan ulang', f'Percobaan {session.attempt}; nonce server diperbarui.', session.id)
    return {**session.public(), 'retry': plan}


class Retake(BaseModel):
    stage: str = Field(pattern='^(document|liveness|holding)$')
    nonce: str = Field(min_length=20, max_length=100)


@router.post('/sessions/{session_id}/retake')
def retake(session_id: str, body: Retake, request: Request):
    sessions, _, repository = services(request)
    with sessions.lock:
        sessions.check_revision(sessions.get(session_id), request)
        session = sessions.reset(session_id, body.stage, body.nonce)
    repository.audit('Capture diambil ulang', f'Tahap {body.stage}; generasi {session.revision}; nonce diperbarui.', session.id)
    return session.public()


@router.post('/sessions/{session_id}/document')
async def document(session_id: str, request: Request, image: UploadFile = File(...)):
    sessions, verifier, repository = services(request)
    session = sessions.get(session_id)
    sessions.check_revision(session, request)
    revision = session.revision
    nonce = session.nonce
    live_token = session.liveness_nonce
    if session.consumed or session.processing or session.liveness_processing:
        raise HTTPException(409, 'Sesi sudah diproses. Gunakan retry atau sesi baru.')
    decoded, digest = await image_upload(image)
    try:
        result = await run_in_threadpool(verifier.document, decoded)
    except CaptureError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    with sessions.lock:
        sessions.get(session_id)
        sessions.check_revision(session, request)
        if session.revision != revision or session.nonce != nonce or session.liveness_nonce != live_token or session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409, 'Capture berubah atau sesi sedang diproses.')
        session.document = decoded
        session.document_result = result
        # Live-person evidence is independent of the card image. Replacing the
        # document still forces fresh face/NIK comparisons in final verify.
        if not (session.liveness_result and session.liveness_result.get('passed')):
            sessions.clear_liveness(session)
    repository.audit('OCR selesai', f'NIK terbaca; confidence {result["confidence"]:.3f}. Gambar tidak disimpan ke disk.', session.id)
    return result


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
        result = await run_in_threadpool(verifier.inspect_capture, decoded, context=='holding')
        with sessions.lock:
            if session.revision != revision:
                raise HTTPException(409, 'Capture sudah diambil ulang.')
        return result
    except ModelUnavailable as exc:
        raise HTTPException(503,str(exc)) from exc


class IdentityCorrection(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    birth: str = Field(default='', max_length=10)
    address: str = Field(default='', max_length=200)


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
    holding_image, _ = await image_upload(holding)
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
    try:
        repository.audit('Verifikasi dimulai', f'Percobaan {session.attempt}; nonce dikonsumsi.', session.id)
        result = await run_in_threadpool(verifier.run, session, face_image, holding_image, decoded_frames, metadata)
        session.last_result = result
        return result
    finally:
        with sessions.lock:
            session.processing = False


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
    _, _, repository = services(request)
    if len(body.note.strip()) < 5:
        raise HTTPException(422, 'Catatan minimal 5 karakter.')
    try:
        result = repository.update_result(result_id, {'status': body.decision, 'note': body.note.strip(), 'reviewed_at': utcnow()})
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    repository.audit('Keputusan petugas', body.decision+': '+body.note.strip(), result_id)
    return result


class Reservation(BaseModel):
    at: str


@router.post('/records/{result_id}/schedule')
def schedule(result_id: str, body: Reservation, request: Request):
    _, _, repository = services(request)
    try:
        at = datetime.fromisoformat(body.at)
        if at.tzinfo is None or at <= datetime.now(timezone.utc):
            raise ValueError('Pilih jadwal mendatang dengan zona waktu.')
        result = repository.update_result(result_id, {'status': 'scheduled', 'schedule': at.isoformat()})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    repository.audit('Reservasi pemeriksaan', at.isoformat(), result_id)
    return result
