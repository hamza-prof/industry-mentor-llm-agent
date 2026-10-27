from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from app import prompts
from app.api import ApiError
from app.db import get_session
from app.prompts import DEFAULT_PROMPTS, PromptInvalid

router = APIRouter(prefix="/api/prompts", tags=["prompts"])
SessionDep = Annotated[Session, Depends(get_session)]


class PromptOut(BaseModel):
    key: str
    description: str
    required: list[str]
    optional: list[str]
    active_version: int
    system: str
    user: str


class PromptVersionOut(BaseModel):
    version: int
    system: str
    user: str
    created_at: datetime


class PromptIn(BaseModel):
    system: str = ""
    user: str


def _key(key: str) -> str:
    if key not in DEFAULT_PROMPTS:
        raise ApiError(404, "NOT_FOUND", f"Unknown prompt '{key}'.")
    return key


def _out(session: Session, key: str) -> PromptOut:
    spec, active = DEFAULT_PROMPTS[key], prompts.get_active(session, key)
    return PromptOut(
        key=key,
        description=spec.description,
        required=sorted(spec.required),
        optional=sorted(spec.optional | {"language"}),
        active_version=active.version,
        system=active.system,
        user=active.user,
    )


@router.get("", response_model=list[PromptOut])
def list_prompts(session: SessionDep):
    return [_out(session, key) for key in DEFAULT_PROMPTS]


@router.get("/{key}", response_model=PromptOut)
def get_prompt(key: str, session: SessionDep):
    return _out(session, _key(key))


@router.put("/{key}", response_model=PromptOut)
def update_prompt(key: str, body: PromptIn, session: SessionDep):
    try:
        prompts.save_version(session, _key(key), body.system, body.user)
    except PromptInvalid as e:
        v = e.validation
        raise ApiError(
            422, "PROMPT_INVALID", str(e), missing=v.missing, unknown=v.unknown, errors=v.errors
        ) from e
    return _out(session, key)


@router.post("/{key}/reset", response_model=PromptOut)
def reset_prompt(key: str, session: SessionDep):
    prompts.reset(session, _key(key))
    return _out(session, key)


@router.get("/{key}/versions", response_model=list[PromptVersionOut])
def list_versions(key: str, session: SessionDep):
    return prompts.list_versions(session, _key(key))


@router.post("/{key}/activate/{version}", response_model=PromptOut)
def activate_version(key: str, version: int, session: SessionDep):
    try:
        prompts.activate(session, _key(key), version)
    except LookupError as e:
        raise ApiError(404, "NOT_FOUND", str(e)) from e
    return _out(session, key)
