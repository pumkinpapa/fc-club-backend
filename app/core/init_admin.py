"""
초기 관리자 계정 생성 스크립트

서버 시작 시 자동 실행되어 관리자 계정이 없으면 생성합니다.
"""

from sqlalchemy.orm import Session
from app.models import Member
from datetime import datetime, timezone


def create_initial_admin(db: Session):
    """관리자 계정이 없으면 생성"""
    admin = db.query(Member).filter(Member.role == "회장").first()
    if not admin:
        admin = Member(
            name="관리자",
            birth="1990-01-01",
            phone="01000000001",
            role="회장",
            status="승인",
            join_date=datetime.now(timezone.utc),
            note="초기 관리자 계정",
        )
        db.add(admin)
        db.commit()
        print("[초기화] 관리자 계정 생성 완료 - 전화번호: 01000000001")
    else:
        print(f"[초기화] 관리자 계정 존재 - {admin.name} ({admin.phone})")
