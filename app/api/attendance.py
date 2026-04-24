"""
📍 GPS 지각 체크 API

- POST   /api/attendance/check-in              -> 자동 체크인 (모든 회원)
- GET    /api/attendance/match/{match_id}      -> 경기별 출석 현황 (모든 회원)
- GET    /api/attendance/my-status/{match_id}  -> 본인 체크인 상태 (앱 실행 시)
- PUT    /api/attendance/{id}                  -> 관리자 수동 수정
- DELETE /api/attendance/{id}                  -> 관리자 삭제
- POST   /api/attendance/manual                -> 관리자가 대신 체크인

경기 정보 수정:
- PUT    /api/matches/{id}/settings            -> 경기 시간/경기장 수정 (관리자)
"""
from datetime import datetime, timedelta, date
from math import radians, cos, sin, asin, sqrt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.models import Member, Match, MatchRecord, AttendanceCheck

router = APIRouter(prefix="/api/attendance", tags=["출석체크"])

SYS_ADMIN_PHONE = "01000000001"


# ============================================================
# Helper
# ============================================================

def is_sys_admin(user: Member) -> bool:
    return user.phone == SYS_ADMIN_PHONE


def is_admin_user(user: Member) -> bool:
    """관리자 권한: 회장/총무/관리자 또는 시스템관리자"""
    if user.phone == SYS_ADMIN_PHONE:
        return True
    if user.role in ("회장", "관리자", "총무"):
        return True
    return False


def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """두 GPS 좌표 간 거리(미터) - Haversine 공식"""
    R = 6371000  # 지구 반지름(m)
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return int(R * 2 * asin(sqrt(a)))


def judge_check_in(match: Match, check_time: datetime) -> tuple:
    """
    체크인 시간으로 지각 판정
    Returns: (status, late_minutes)
    Raises: HTTPException if out of allowed range
    """
    # 경기 시작 시간 파싱
    try:
        hour, minute = map(int, (match.match_time or "06:30").split(":"))
    except Exception:
        hour, minute = 8, 0

    match_datetime = datetime.combine(
        match.match_date,
        datetime.min.time().replace(hour=hour, minute=minute)
    )

    # 체크인 허용 범위: 경기 ±1시간
    allowed_start = match_datetime - timedelta(hours=1)
    allowed_end = match_datetime + timedelta(hours=1)

    if check_time < allowed_start:
        raise HTTPException(
            status_code=400,
            detail=f"체크인 가능 시간이 아닙니다. ({allowed_start.strftime('%H:%M')}부터 가능)"
        )
    if check_time > allowed_end:
        raise HTTPException(
            status_code=400,
            detail=f"체크인 가능 시간이 아닙니다. ({allowed_end.strftime('%H:%M')}까지였습니다)"
        )

    # 지각 판정
    if check_time <= match_datetime:
        return ("정시", 0)
    else:
        late = int((check_time - match_datetime).total_seconds() / 60)
        return ("지각", late)


# ============================================================
# Request/Response Models
# ============================================================

class AttendanceCheckOut(BaseModel):
    id: int
    match_id: int
    member_id: int
    member_name: str
    check_time: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    accuracy_meters: Optional[float] = None
    distance_meters: int
    status: str
    late_minutes: int
    check_method: str

    class Config:
        from_attributes = True


class CheckInRequest(BaseModel):
    match_id: int
    latitude: float
    longitude: float
    accuracy: Optional[float] = None


class CheckInResponse(BaseModel):
    id: int
    status: str
    check_time: str
    distance_meters: int
    late_minutes: int
    venue_name: str
    message: str


class ManualCheckInRequest(BaseModel):
    match_id: int
    member_id: int
    status: str = Field(..., description="'정시' or '지각'")
    late_minutes: int = Field(default=0, ge=0)


class UpdateAttendanceRequest(BaseModel):
    status: str
    late_minutes: int = Field(default=0, ge=0)


class MatchSettingsRequest(BaseModel):
    match_time: Optional[str] = Field(default=None, description="HH:MM 형식")
    venue_name: Optional[str] = Field(default=None, max_length=100)
    venue_lat: Optional[float] = None
    venue_lng: Optional[float] = None
    venue_radius: Optional[int] = Field(default=None, ge=10, le=5000)


# ============================================================
# API Endpoints
# ============================================================

@router.post("/check-in", response_model=CheckInResponse)
async def check_in(
    req: CheckInRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """자동 체크인 - 로그인 회원 누구나 가능"""
    match = db.query(Match).filter(Match.id == req.match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    # 오늘 경기인지 체크 (지난/미래 경기 방지)
    if match.match_date != date.today():
        raise HTTPException(status_code=400, detail="오늘 경기만 체크인 가능합니다.")

    # 이미 체크인했는지 확인
    existing = db.query(AttendanceCheck).filter(
        AttendanceCheck.match_id == req.match_id,
        AttendanceCheck.member_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"이미 {existing.check_time.strftime('%H:%M')}에 체크인했습니다."
        )

    # 거리 계산
    venue_lat = match.venue_lat or 37.5448
    venue_lng = match.venue_lng or 127.0378
    venue_radius = match.venue_radius or 200
    distance = calculate_distance(req.latitude, req.longitude, venue_lat, venue_lng)

    # 반경 체크
    if distance > venue_radius:
        raise HTTPException(
            status_code=400,
            detail=f"경기장에서 {distance}m 떨어져 있습니다. ({venue_radius}m 이내에서 체크인해주세요)"
        )

    # 시간 판정 (서버 시간 기준)
    now = datetime.now()
    status, late_minutes = judge_check_in(match, now)

    # 저장
    new_check = AttendanceCheck(
        match_id=req.match_id,
        member_id=current_user.id,
        check_time=now,
        latitude=req.latitude,
        longitude=req.longitude,
        accuracy_meters=req.accuracy,
        distance_meters=distance,
        status=status,
        late_minutes=late_minutes,
        check_method="auto",
    )
    db.add(new_check)
    try:
        db.commit()
        db.refresh(new_check)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="이미 체크인 기록이 있습니다.")

    # 메시지 생성
    if status == "정시":
        message = f"정시 도착 체크 완료 ({distance}m)"
    else:
        message = f"{late_minutes}분 지각 체크인 ({distance}m)"

    return CheckInResponse(
        id=new_check.id,
        status=status,
        check_time=now.strftime("%H:%M:%S"),
        distance_meters=distance,
        late_minutes=late_minutes,
        venue_name=match.venue_name or "서울숲",
        message=message,
    )


@router.get("/my-status/{match_id}")
async def get_my_status(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """앱 실행 시 본인 체크인 상태 확인 (자동 체크인 판단용)"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"checked_in": False, "match_exists": False}

    existing = db.query(AttendanceCheck).filter(
        AttendanceCheck.match_id == match_id,
        AttendanceCheck.member_id == current_user.id,
    ).first()

    if not existing:
        return {
            "checked_in": False,
            "match_exists": True,
            "match_date": match.match_date.isoformat(),
            "match_time": match.match_time or "06:30",
            "venue_name": match.venue_name or "서울숲",
            "venue_lat": match.venue_lat or 37.5448,
            "venue_lng": match.venue_lng or 127.0378,
            "venue_radius": match.venue_radius or 200,
        }

    return {
        "checked_in": True,
        "match_exists": True,
        "id": existing.id,
        "status": existing.status,
        "check_time": existing.check_time.strftime("%H:%M:%S"),
        "distance_meters": existing.distance_meters,
        "late_minutes": existing.late_minutes,
        "venue_name": match.venue_name or "서울숲",
    }


@router.get("/match/{match_id}")
async def get_match_attendance(
    match_id: int,
    db: Session = Depends(get_db),
    _user: Member = Depends(get_current_user),
):
    """경기별 출석 현황 조회 (결과탭용)"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    # 체크인 기록 + 회원 정보 조인
    checks = db.query(AttendanceCheck, Member).join(
        Member, AttendanceCheck.member_id == Member.id
    ).filter(AttendanceCheck.match_id == match_id).order_by(
        AttendanceCheck.late_minutes.desc(),
        AttendanceCheck.check_time,
    ).all()

    # 참석한 회원 중 체크 안 한 사람 찾기
    attending_records = db.query(MatchRecord, Member).join(
        Member, MatchRecord.member_id == Member.id
    ).filter(
        MatchRecord.match_id == match_id,
        MatchRecord.attendance == "참석",
    ).all()

    checked_member_ids = {c.member_id for c, _ in checks}
    unchecked = [
        {"member_id": m.id, "member_name": m.name}
        for mr, m in attending_records
        if m.id not in checked_member_ids
    ]

    result_checks = []
    ontime_count = 0
    late_count = 0
    for c, m in checks:
        result_checks.append({
            "id": c.id,
            "member_id": c.member_id,
            "member_name": m.name,
            "check_time": c.check_time.strftime("%H:%M"),
            "distance_meters": c.distance_meters,
            "status": c.status,
            "late_minutes": c.late_minutes,
            "check_method": c.check_method,
        })
        if c.status == "정시":
            ontime_count += 1
        else:
            late_count += 1

    return {
        "match_id": match_id,
        "match_date": match.match_date.isoformat(),
        "match_time": match.match_time or "06:30",
        "venue_name": match.venue_name or "서울숲",
        "summary": {
            "ontime": ontime_count,
            "late": late_count,
            "unchecked": len(unchecked),
        },
        "checks": result_checks,
        "unchecked": unchecked,
    }


@router.put("/{check_id}")
async def update_attendance(
    check_id: int,
    req: UpdateAttendanceRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """관리자 수동 수정 (관리자/시스템관리자)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="관리자만 수정할 수 있습니다.")

    check = db.query(AttendanceCheck).filter(AttendanceCheck.id == check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="체크인 기록을 찾을 수 없습니다.")

    if req.status not in ("정시", "지각"):
        raise HTTPException(status_code=400, detail="status는 '정시' 또는 '지각'만 가능합니다.")

    check.status = req.status
    check.late_minutes = req.late_minutes if req.status == "지각" else 0
    check.check_method = "admin"
    db.commit()
    db.refresh(check)
    return {"message": "수정되었습니다.", "id": check.id, "status": check.status}


@router.delete("/{check_id}")
async def delete_attendance(
    check_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """관리자 삭제 (관리자/시스템관리자)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="관리자만 삭제할 수 있습니다.")

    check = db.query(AttendanceCheck).filter(AttendanceCheck.id == check_id).first()
    if not check:
        raise HTTPException(status_code=404, detail="체크인 기록을 찾을 수 없습니다.")

    db.delete(check)
    db.commit()
    return {"message": "삭제되었습니다.", "id": check_id}


@router.post("/manual")
async def manual_check_in(
    req: ManualCheckInRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """관리자가 GPS 실패한 회원 대신 체크인 (관리자/시스템관리자)"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="관리자만 가능합니다.")

    match = db.query(Match).filter(Match.id == req.match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    member = db.query(Member).filter(Member.id == req.member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다.")

    if req.status not in ("정시", "지각"):
        raise HTTPException(status_code=400, detail="status는 '정시' 또는 '지각'만 가능합니다.")

    # 이미 체크인 있으면 거부
    existing = db.query(AttendanceCheck).filter(
        AttendanceCheck.match_id == req.match_id,
        AttendanceCheck.member_id == req.member_id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 체크인 기록이 있습니다.")

    new_check = AttendanceCheck(
        match_id=req.match_id,
        member_id=req.member_id,
        check_time=datetime.now(),
        latitude=match.venue_lat or 37.5448,
        longitude=match.venue_lng or 127.0378,
        accuracy_meters=0,
        distance_meters=0,
        status=req.status,
        late_minutes=req.late_minutes if req.status == "지각" else 0,
        check_method="admin",
    )
    db.add(new_check)
    db.commit()
    db.refresh(new_check)
    return {
        "message": f"{member.name}님을 {req.status}으로 처리했습니다.",
        "id": new_check.id,
    }
