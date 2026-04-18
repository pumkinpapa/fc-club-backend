"""
FC 동호회 - 축구 동호회 운영 관리 백엔드

FastAPI 앱 진입점
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, SessionLocal
from app.api import auth, members, matches, rankings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.core.init_admin import create_initial_admin

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    init_db()
    db = SessionLocal()
    try:
        create_initial_admin(db)
    finally:
        db.close()
    start_scheduler()
    print(f"  {settings.app_name} 서버 시작!")
    yield
    stop_scheduler()
    print(f"  {settings.app_name} 서버 종료")


app = FastAPI(
    title=f"{settings.app_name} API",
    description="축구 동호회 운영 관리 백엔드 서버",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(members.router)
app.include_router(matches.router)
app.include_router(rankings.router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "2.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
