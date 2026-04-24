"""
GPS 지각 체크 기능 마이그레이션
- matches 테이블에 5개 필드 추가 (match_time, venue_*)
- attendance_checks 테이블 신규 생성
- 기존 migration_positions.py와 동일한 패턴 (앱 시작 시 자동 실행)
"""
from sqlalchemy import text
from app.core.database import engine


def run_attendance_migration():
    """matches 테이블 확장 + attendance_checks 테이블 생성"""
    print("📍 [migration_attendance] 시작...")

    with engine.begin() as conn:
        # 1. matches 테이블에 컬럼 추가 (IF NOT EXISTS)
        print("   📅 matches 테이블 확장...")

        # PostgreSQL은 ADD COLUMN IF NOT EXISTS 지원
        columns_to_add = [
            ("match_time", "VARCHAR(10) DEFAULT '06:30'"),
            ("venue_name", "VARCHAR(100) DEFAULT '서울숲'"),
            ("venue_lat", "DOUBLE PRECISION DEFAULT 37.546220"),
            ("venue_lng", "DOUBLE PRECISION DEFAULT 127.040813"),
            ("venue_radius", "INTEGER DEFAULT 100"),
        ]
        for col_name, col_def in columns_to_add:
            try:
                conn.execute(text(
                    f"ALTER TABLE matches ADD COLUMN IF NOT EXISTS {col_name} {col_def};"
                ))
                print(f"      ✓ {col_name}")
            except Exception as e:
                print(f"      ⚠️  {col_name} 추가 실패 (이미 있음?): {e}")

        # 1-1. 기본 시간 보정: 08:00으로 저장된 경기 → 06:30으로 일회성 업데이트
        # (이전 버전에서 08:00으로 마이그레이션된 기존 경기 보정)
        try:
            result = conn.execute(text(
                "UPDATE matches SET match_time='06:30' WHERE match_time='08:00';"
            ))
            updated = result.rowcount or 0
            if updated > 0:
                print(f"      ↻ 기존 경기 {updated}개 시간을 06:30으로 업데이트")
        except Exception as e:
            print(f"      ⚠️  시간 보정 스킵: {e}")

        # 1-2. 기본 좌표/반경 보정: 이전 좌표로 저장된 경기 → 정확한 좌표로 업데이트
        # (이전 버전 37.5448, 127.0378, 200m → 37.546220, 127.040813, 100m)
        try:
            result = conn.execute(text("""
                UPDATE matches
                SET venue_lat=37.546220, venue_lng=127.040813, venue_radius=100
                WHERE venue_lat=37.5448 AND venue_lng=127.0378;
            """))
            updated = result.rowcount or 0
            if updated > 0:
                print(f"      ↻ 기존 경기 {updated}개 좌표/반경을 새 값으로 업데이트")
        except Exception as e:
            print(f"      ⚠️  좌표 보정 스킵: {e}")

        # 2. attendance_checks 테이블 생성
        print("   📍 attendance_checks 테이블 생성...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS attendance_checks (
                id SERIAL PRIMARY KEY,
                match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
                check_time TIMESTAMP NOT NULL,
                latitude DOUBLE PRECISION NOT NULL,
                longitude DOUBLE PRECISION NOT NULL,
                accuracy_meters DOUBLE PRECISION,
                distance_meters INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL,
                late_minutes INTEGER DEFAULT 0,
                check_method VARCHAR(20) DEFAULT 'auto',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_attendance_match_member UNIQUE (match_id, member_id)
            );
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attendance_checks_match_id "
            "ON attendance_checks(match_id);"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attendance_checks_member_id "
            "ON attendance_checks(member_id);"
        ))
        print("      ✓ attendance_checks OK")

        # 3. 검증
        result = conn.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name = 'attendance_checks'
        """))
        if result.scalar() > 0:
            print("   ✅ 검증 완료")
        else:
            print("   ⚠️  테이블 생성 확인 실패")

    print("📍 [migration_attendance] 완료")


if __name__ == "__main__":
    run_attendance_migration()
