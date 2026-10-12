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
        if session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409,'Sesi sedang atau sudah diproses.')
        if session.document is None:
            raise HTTPException(422,'Baca KTP sebelum merekam liveness.')
        if session.liveness_attempts>=MAX_ATTEMPTS:
            raise HTTPException(429,'Batas tiga rekaman liveness tercapai. Mulai sesi baru.')
        session.liveness_attempts+=1
        session.liveness_nonce=secrets.token_urlsafe(32)
        session.liveness_started=time.monotonic()
        session.liveness_result=None
        session.liveness_hashes=[]
        session.challenges=secrets.SystemRandom().sample(['blink','turn','smile'],3)
        result={**session.public(),'capture_nonce':session.liveness_nonce,'liveness_attempts':session.liveness_attempts}
    repository.audit('Rekaman liveness dimulai',f'Percobaan rekaman {session.liveness_attempts}; tantangan server.',session.id)
    return result


@router.post('/sessions/{session_id}/liveness/check')
async def check_liveness(session_id: str, request: Request, capture_nonce: str = Form(...),
                         manifest: str = Form(...), selfie: UploadFile = File(...), frames: list[UploadFile] = File(...)):
    sessions,verifier,repository=services(request)
    session=sessions.get(session_id)
    metadata=frame_manifest(manifest,len(frames),session.challenges)
    selfie_image,selfie_hash=await image_upload(selfie)
    decoded,hashes=await frame_uploads(frames)
    span=(metadata[-1]['t_ms']-metadata[0]['t_ms'])/1000
    with sessions.lock:
        session=sessions.get(session_id)
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
    session = sessions.retry(session_id)
    repository.audit('Percobaan ulang', f'Percobaan {session.attempt}; nonce server diperbarui.', session.id)
    return session.public()


@router.post('/sessions/{session_id}/document')
async def document(session_id: str, request: Request, image: UploadFile = File(...)):
    sessions, verifier, repository = services(request)
    session = sessions.get(session_id)
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
        if session.consumed or session.processing or session.liveness_processing:
            raise HTTPException(409, 'Sesi sedang diproses.')
        session.document = decoded
        session.document_result = result
        session.liveness_result = None
        session.liveness_hashes = []
        session.liveness_nonce = None
    repository.audit('OCR selesai', f'NIK terbaca; confidence {result["confidence"]:.3f}. Gambar tidak disimpan ke disk.', session.id)
    return result


@router.post('/sessions/{session_id}/capture-check')
async def capture_check(session_id: str, request: Request, image: UploadFile = File(...), context: str = Form('selfie')):
    sessions, verifier, _ = services(request)
    if context not in ['selfie','holding']:
        raise HTTPException(422,'Jenis capture tidak valid.')
    with sessions.lock:
        session=sessions.get(session_id)
        if session.processing or session.consumed:
            raise HTTPException(409,'Sesi sudah diproses. Buat sesi baru atau retry.')
        now=time.monotonic()
        if now-session.last_preview<.5:
            raise HTTPException(429,'Pemeriksaan kamera terlalu cepat.')
        session.last_preview=now
    decoded,_=await image_upload(image,MAX_FRAME_BYTES)
    try:
        return await run_in_threadpool(verifier.inspect_capture, decoded, context=='holding')
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
        if session.consumed or not session.document_result:
            raise HTTPException(409, 'OCR belum selesai atau sesi sudah diproses.')
        session.document_result['fields'].update(body.model_dump())
    return session.document_result['fields']


@router.post('/sessions/{session_id}/verify')
async def verify(session_id: str, request: Request, nonce: str = Form(...),
                 manifest: str = Form(...), selfie: UploadFile = File(...),
                 holding: UploadFile = File(...), frames: list[UploadFile] = File(...)):
    sessions, verifier, repository = services(request)
    session = sessions.get(session_id)
    metadata=frame_manifest(manifest,len(frames),session.challenges)
    face_image,selfie_hash=await image_upload(selfie)
    holding_image,_=await image_upload(holding)
    decoded_frames,hashes=await frame_uploads(frames)
    with sessions.lock:
        if not session.liveness_result or not session.liveness_result.get('passed'):
            raise HTTPException(422,'Liveness belum lolos pemeriksaan model. Rekam ulang sebelum melanjutkan.')
        if hashes!=session.liveness_hashes or selfie_hash!=session.liveness_selfie or manifest_digest(metadata)!=session.liveness_manifest:
            raise HTTPException(409,'Capture berbeda dari rekaman yang diperiksa. Rekam ulang liveness.')
        session = sessions.consume(session_id, nonce)
    try:
        repository.audit('Verifikasi dimulai', f'Percobaan {session.attempt}; {len(frames)} frame; nonce dikonsumsi.', session.id)
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
