"""
FC 동호회 - 축구 동호회 운영 관리 백엔드

FastAPI 앱 진입점
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db
from app.api import auth, members, matches, rankings
from app.services.scheduler import start_scheduler, stop_scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 실행"""
    # 시작
    init_db()
    start_scheduler()
    print(f"🚀 {settings.app_name} 서버 시작!")
    yield
    # 종료
    stop_scheduler()
    print(f"👋 {settings.app_name} 서버 종료")


app = FastAPI(
    title=f"{settings.app_name} API",
    description="축구 동호회 운영 관리 백엔드 서버",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 설정 (프론트엔드 연동용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 특정 도메인으로 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router)
app.include_router(members.router)
app.include_router(matches.router)
app.include_router(rankings.router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
