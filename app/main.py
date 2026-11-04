from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.database.session import init_db
from app.api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Инициализация схемы БД при запуске
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend первого прототипа платформы концептуального проектирования «Недра».",
    lifespan=lifespan,
)

# Разрешаем CORS для frontend первого прототипа
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение маршрутов API v1
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/health", tags=["system"])
def root_health():
    """Проверка доступности корневого сервиса."""
    return {"status": "ok"}
