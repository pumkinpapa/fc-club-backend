"""
DB 마이그레이션: 포지션 필드 추가

- Member.positions: 선호 포지션 (쉼표 구분, 최대 2개)
- MatchRecord.position: 편성 시 배정 포지션
- Match.formations: 팀별 포메이션 JSON

앱 시작 시 자동 실행됩니다.
PostgreSQL / SQLite 모두 지원.
"""

from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from app.core.database import engine


def add_column_if_not_exists(conn, table: str, column: str, col_type: str, default: str = "''"):
    """컬럼이 없으면 추가 (PostgreSQL / SQLite 호환)"""
    inspector = inspect(engine)
    existing_cols = [c["name"] for c in inspector.get_columns(table)]
    if column in existing_cols:
        return False

    dialect = engine.dialect.name
    if dialect == "postgresql":
        sql = f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS "{column}" {col_type} DEFAULT {default}'
    else:  # sqlite
        sql = f'ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}'

    conn.execute(text(sql))
    print(f"✅ 컬럼 추가: {table}.{column}")
    return True


def run_position_migration():
    """포지션 관련 컬럼 자동 추가"""
    try:
        with engine.begin() as conn:
            # Member.positions (선호 포지션, 쉼표 구분)
            add_column_if_not_exists(conn, "members", "positions", "VARCHAR(50)", "''")

            # MatchRecord.position (편성 시 배정 포지션)
            add_column_if_not_exists(conn, "match_records", "position", "VARCHAR(20)", "''")

            # Match.formations (팀별 포메이션 JSON)
            add_column_if_not_exists(conn, "matches", "formations", "TEXT", "''")

        print("✅ 포지션 마이그레이션 완료")
    except Exception as e:
        print(f"⚠️ 포지션 마이그레이션 실패 (무시하고 진행): {e}")


if __name__ == "__main__":
    run_position_migration()
