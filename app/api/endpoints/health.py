from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check():
    """Проверка жизнеспособности сервиса."""
    return {"status": "ok"}
