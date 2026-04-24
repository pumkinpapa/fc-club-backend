"""
구장 예약 달력 기능 마이그레이션
- court_reservations 테이블 생성 (IF NOT EXISTS)
- 기존 migration_positions.py와 동일한 패턴 (앱 시작 시 자동 실행)
"""
from sqlalchemy import text
from app.core.database import engine


def run_reservation_migration():
    """court_reservations 테이블 생성 및 검증"""
    print("🏟️  [migration_reservations] 시작...")
    with engine.begin() as conn:
        # 테이블 생성
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS court_reservations (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                time_slot VARCHAR(20) NOT NULL,
                reserver_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                reserver_name VARCHAR(50) NOT NULL,
                court_name VARCHAR(100) NOT NULL DEFAULT '서울숲',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_reservation_date_slot UNIQUE (date, time_slot)
            );
        """))
        # 인덱스
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_court_reservations_date "
            "ON court_reservations(date);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_court_reservations_reserver_id "
            "ON court_reservations(reserver_id);"
        ))

        # 검증
        result = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'court_reservations'
        """))
        exists = result.scalar() > 0
        if exists:
            print("   ✅ court_reservations OK")
        else:
            print("   ⚠️  court_reservations 테이블 생성 확인 실패")

    print("🏟️  [migration_reservations] 완료")


if __name__ == "__main__":
    run_reservation_migration()
