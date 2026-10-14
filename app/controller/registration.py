from fastapi import APIRouter, Request, Security
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
    return RegistrationService(request.app.state.sessions, request.app.state.repository, request.app.state.workflow, actor(request)).status(registration_id)


@router.get('/applications/{application_id}/registration-context')
def identity_context(application_id: str, request: Request):
    return RegistrationService(request.app.state.sessions, request.app.state.repository, request.app.state.workflow, actor(request)).identity_context(application_id)
