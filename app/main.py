from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.database import init_db, SessionLocal
from app.api import auth, members, matches, rankings, reservations, attendance, match_settings
from app.services.scheduler import start_scheduler, stop_scheduler
from app.core.init_admin import create_initial_admin
from app.migration_positions import run_position_migration
run_position_migration()  # ★ 앱 시작 시 자동 실행
from app.migration_reservations import run_reservation_migration
run_reservation_migration()  # ★ 구장 예약 테이블 생성
from app.migration_attendance import run_attendance_migration
run_attendance_migration()

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        create_initial_admin(db)
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="FC Club API", version="2.0.0", lifespan=lifespan)

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
app.include_router(reservations.router)
app.include_router(attendance.router)       # ★ 추가
app.include_router(match_settings.router)   # ★ 추가


@app.get("/")
async def root():
    return {"name": "FC Club", "status": "ok"}
