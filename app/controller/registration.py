from fastapi import APIRouter, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from app.model.registration import RegistrationRequest
from app.services.registration import RegistrationService
from app.services.auth import actor

router = APIRouter(prefix='/api', dependencies=[Security(APIKeyHeader(name='X-Local-Client', auto_error=False))])


@router.post('/registrations')
def submit(body: RegistrationRequest, request: Request):
    return RegistrationService(request.app.state.sessions, request.app.state.repository, request.app.state.workflow, actor(request)).submit(body)


@router.get('/registrations/{registration_id}')
def status(registration_id: str, request: Request):
    result = request.app.state.repository.registration(registration_id)
    if not result or result.get('owner_id') != actor(request)['id']:
        raise HTTPException(404, 'Nomor pendaftaran demo tidak ditemukan pada server lokal ini.')
    return result
