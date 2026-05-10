from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# ────────────────────────────────────────────
# DB 엔진 설정
# ────────────────────────────────────────────
# Render 무료 인스턴스는 비활성 시 슬립 모드로 진입하며,
# 깨어날 때 Neon DB와의 SSL 커넥션이 끊긴 상태가 자주 발생함.
# 이때 첫 쿼리에서 "SSL connection has been closed unexpectedly" 에러가 발생.
#
# 해결: 아래 풀 설정을 추가하여 매 쿼리 전 커넥션 유효성 검증.
engine = create_engine(
    settings.database_url,
    # ★ 핵심: 매 쿼리 전 커넥션 살아있는지 체크 (1ms도 안 걸림, 안전)
    pool_pre_ping=True,
    # 5분(300초) 후 커넥션 자동 재생성 → 오래된 커넥션의 SSL 끊김 방지
    pool_recycle=300,
    # 기본 풀 크기 (동시 5개 커넥션 유지)
    pool_size=5,
    # 추가 허용 커넥션 (트래픽 급증 대응)
    max_overflow=10,
    # PostgreSQL TCP keepalive 설정 (커넥션 끊김 조기 감지)
    connect_args={
        "connect_timeout": 10,       # 연결 타임아웃 10초
        "keepalives": 1,             # TCP keepalive 활성화
        "keepalives_idle": 30,       # 30초마다 keepalive 신호
        "keepalives_interval": 10,   # 10초 간격으로 재시도
        "keepalives_count": 5,       # 5번 실패 시 끊김 판정
    },
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
