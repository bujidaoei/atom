import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import settings
from app.db import Base, engine
from app.routers import auth, projects, settings as settings_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("atom")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    if settings.secret == "dev-only-change-me":
        logger.warning("ATOM_SECRET is still the development default")
    yield


app = FastAPI(title="Atom Demo", lifespan=lifespan)
app.include_router(auth.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(projects.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}
