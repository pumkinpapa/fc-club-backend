from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False}  # SQLite 전용
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI Dependency: DB 세션 제공"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """앱 시작 시 테이블 생성"""
    Base.metadata.create_all(bind=engine)
