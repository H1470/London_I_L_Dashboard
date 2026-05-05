from fastapi import APIRouter

from app.data.fake_indices import get_indices_snapshot

router = APIRouter()


@router.get("/indices")
def indices():
    return get_indices_snapshot()
