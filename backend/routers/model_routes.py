from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth_utils import require_admin
from model_routes import public_model_routes, save_model_routes
from models import User

router = APIRouter(prefix="/api/model-routes", tags=["model-routes"])


class ModelRoutesUpdate(BaseModel):
    default_chat_model: str | None = None
    default_intent_model: str | None = None
    default_vision_model: str | None = None
    chat_models: list[str] | None = None
    vision_models: list[str] | None = None


@router.get("")
def get_model_routes():
    return public_model_routes()


@router.put("")
def update_model_routes(body: ModelRoutesUpdate, _: User = Depends(require_admin)) -> dict[str, Any]:
    save_model_routes(body.dict(exclude_none=True))
    return public_model_routes()
