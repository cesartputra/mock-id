from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.auth import actor

router = APIRouter(prefix="/api/verification-entry")


def applicant(request):
    who = actor(request)
    if who["role"] not in ["applicant", "admin"]:
        raise HTTPException(403, "CAPTCHA digunakan sebelum capture pemohon.")
    return who


class PuzzleAnswer(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=100)
    offset: int = Field(ge=0, le=268, strict=True)


@router.post("/challenge")
def challenge(request: Request):
    who = applicant(request)
    request.app.state.auth.limit("captcha-issue:" + who["id"], 20, 60)
    return request.app.state.verification_entry.issue(who["id"])


@router.post("/solve")
def solve(request: Request, body: PuzzleAnswer):
    who = applicant(request)
    request.app.state.auth.limit("captcha-solve:" + who["id"], 30, 60)
    return request.app.state.verification_entry.solve(who["id"], body.challenge_id, body.offset)
