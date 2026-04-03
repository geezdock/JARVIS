from datetime import datetime, UTC

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ProfileUploadPayload(BaseModel):
    filename: str
    size: int
    type: str
    submittedAt: str


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/candidate/profile-upload")
def candidate_profile_upload(payload: ProfileUploadPayload) -> dict[str, object]:
    return {
        "message": "Profile upload received",
        "received": payload.model_dump(),
        "processedAt": datetime.now(UTC).isoformat(),
    }
