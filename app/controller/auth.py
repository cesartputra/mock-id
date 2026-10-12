import os
from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/auth")


class Credentials(BaseModel):
    login: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=10, max_length=200)


@router.post("/guest")
def guest(request: Request, response: Response):
    token, principal = request.app.state.auth.guest(
        request.cookies.get("mock_id_guest")
    )
    response.set_cookie(
        "mock_id_guest",
        token,
        httponly=True,
        samesite="strict",
        secure=os.getenv("MOCK_ID_MODE", "demo") == "production",
        max_age=30 * 86400,
    )
    return {"principal": principal}


@router.post("/signup")
def signup(body: Credentials, request: Request):
    if os.getenv("MOCK_ID_MODE", "demo") != "demo":
        raise HTTPException(403, "Pembuatan akun melalui aplikasi induk diperlukan.")
    request.app.state.auth.create_user(body.login, body.password)
    return {"created": True, "role": "applicant"}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    token, principal = request.app.state.auth.login(body.login, body.password)
    response.set_cookie(
        "mock_id_session",
        token,
        httponly=True,
        samesite="strict",
        secure=os.getenv("MOCK_ID_MODE", "demo") == "production",
        max_age=43200,
    )
    return {
        "principal": principal,
        "token": token if principal["role"] == "integration" else None,
    }


@router.get("/me")
def me(request: Request):
    return {"principal": request.state.actor}


@router.post("/logout")
def logout(request: Request, response: Response):
    request.app.state.auth.logout(request.state.auth_token)
    response.delete_cookie(
        "mock_id_guest" if request.state.actor.get("guest") else "mock_id_session"
    )
    return {"logged_out": True}
