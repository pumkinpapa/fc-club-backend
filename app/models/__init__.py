from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Enum, ForeignKey, UniqueConstraint, Text, Float
)
from sqlalchemy.orm import relationship
from app.core.database import Base


class Member(Base):
    """회원정보 테이블"""
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, comment="이름")
    birth = Column(String(10), nullable=False, comment="생년월일 (YYYY-MM-DD)")
    phone = Column(String(20), unique=True, nullable=False, comment="핸드폰번호")
    role = Column(
        String(20), default="회원",
        comment="직책 (회장/관리자/회원)"
    )
    status = Column(
        String(20), default="대기",
        comment="가입상태 (대기/승인/거절)"
    )
    kakao_id = Column(String(100), unique=True, nullable=True, comment="카카오 고유 ID")
    join_date = Column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        comment="가입일시"
    )
    note = Column(String(500), default="", comment="비고")

    # 관계
    match_records = relationship("MatchRecord", back_populates="member")

    # ★ 신규 추가
    positions = Column(String(50), default="")  # 선호 포지션 (쉼표 구분, 최대 2개)
    photo = Column(Text, default="")
    
    def __repr__(self):
        return f"<Member(id={self.id}, name={self.name}, role={self.role}, status={self.status})>"


class Match(Base):
    """경기 테이블"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_date = Column(Date, unique=True, nullable=False, comment="경기일자")
    status = Column(
        String(20), default="투표중",
        comment="상태 (투표중/편성완료/경기완료)"
    )
    result_summary = Column(String(200), nullable=True, comment="경기결과 요약")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 관계
    records = relationship("MatchRecord", back_populates="match", cascade="all, delete-orphan")

    # ★ 신규 추가
    formations = Column(Text, default="")  # 팀별 포메이션 JSON. ex: {"1팀":"2-3-1","2팀":"3-2-1"}

    # ★ GPS 지각 체크용 신규 필드
    match_time = Column(String(10), default="06:30")
    venue_name = Column(String(100), default="서울숲")
    venue_lat = Column(Float, default=37.546220)
    venue_lng = Column(Float, default=127.040813)
    venue_radius = Column(Integer, default=100)

    def __repr__(self):
        return f"<Match(id={self.id}, date={self.match_date}, status={self.status})>"


class MatchRecord(Base):
    """경기기록 테이블 (회원별 경기 참여 기록)"""
    __tablename__ = "match_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    attendance = Column(
        String(10), default="미응답",
        comment="참석여부 (참석/불참/미응답)"
    )
    duty = Column(String(50), default="", comment="담당 (골대/음료/없음)")
    team = Column(String(20), default="", comment="팀구분 (1팀/2팀/3팀)")
    match_result = Column(
        String(10), default="",
        comment="경기결과 (승/무/패)"
    )
    # ★ 신규 추가
    position = Column(String(20), default="")  # 편성 시 배정 포지션 (GK, CB, ST 등)

    # 관계
    match = relationship("Match", back_populates="records")
    member = relationship("Member", back_populates="match_records")

    # 같은 경기에 같은 회원은 하나의 레코드만
    __table_args__ = (
        UniqueConstraint("match_id", "member_id", name="uq_match_member"),
    )

    def __repr__(self):
        return f"<MatchRecord(match={self.match_id}, member={self.member_id}, att={self.attendance})>"

# ============================================================
# 🏟️ 구장 예약 (신규)
# ============================================================
class CourtReservation(Base):
    __tablename__ = "court_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    time_slot = Column(String(20), nullable=False)
    reserver_id = Column(Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False)
    reserver_name = Column(String(50), nullable=False)
    court_name = Column(String(100), nullable=False, default="서울숲")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("date", "time_slot", name="uq_reservation_date_slot"),
    )

# ============================================================
# 📍 GPS 출석 체크 (신규)
# ============================================================
class AttendanceCheck(Base):
    __tablename__ = "attendance_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    match_id = Column(Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id", ondelete="CASCADE"), nullable=False)

    # 체크인 정보
    check_time = Column(DateTime, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_meters = Column(Float)
    distance_meters = Column(Integer, nullable=False)

    # 판정 결과
    status = Column(String(20), nullable=False)  # "정시" | "지각"
    late_minutes = Column(Integer, default=0)

    # 로그
    check_method = Column(String(20), default="auto")  # "auto" | "admin"

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("match_id", "member_id", name="uq_attendance_match_member"),
    )
