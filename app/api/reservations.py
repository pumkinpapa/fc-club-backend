"""
🏟️ 구장 예약 달력 API
"""
from datetime import date, datetime
from typing import List
from calendar import monthrange

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Member, CourtReservation

router = APIRouter(prefix="/api/reservations", tags=["구장예약"])

SYS_ADMIN_PHONE = "01000000001"

# 유효한 시간대 슬롯 (고정 3개)
VALID_TIME_SLOTS = ["06-08", "08-10", "10-12"]

# 구장 이름 기본값
DEFAULT_COURT_NAME = "서울숲"


# ============================================================
# Helper
# ============================================================

def is_sys_admin(user: Member) -> bool:
    return user.phone == SYS_ADMIN_PHONE


# ============================================================
# Request/Response Models
# ============================================================

class ReservationOut(BaseModel):
    id: int
    date: str
    time_slot: str
    reserver_id: int
    reserver_name: str
    court_name: str
    created_at: str

    class Config:
        from_attributes = True


class MonthlyReservationsOut(BaseModel):
    year: int
    month: int
    time_slots: List[str]
    reservations: List[ReservationOut]


class CreateReservationRequest(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    time_slot: str = Field(..., description="예: '08-10'")
    court_name: str = Field(default=DEFAULT_COURT_NAME, max_length=100)


class UpdateReservationRequest(BaseModel):
    court_name: str = Field(..., max_length=100)


# ============================================================
# API Endpoints
# ============================================================

@router.get("", response_model=MonthlyReservationsOut)
async def get_monthly_reservations(
    year: int,
    month: int,
    db: Session = Depends(get_db),
    _user: Member = Depends(get_current_user),
):
    """월별 구장 예약 조회 - 모든 로그인 회원 가능"""
    if not (2020 <= year <= 2100):
        raise HTTPException(status_code=400, detail="year 범위 오류 (2020~2100)")
    if not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month 범위 오류 (1~12)")

    _, last_day = monthrange(year, month)
    first_date = date(year, month, 1)
    last_date = date(year, month, last_day)

    rows = db.query(CourtReservation).filter(
        CourtReservation.date >= first_date,
        CourtReservation.date <= last_date,
    ).order_by(CourtReservation.date, CourtReservation.time_slot).all()

    reservations = [
        ReservationOut(
            id=r.id,
            date=r.date.isoformat(),
            time_slot=r.time_slot,
            reserver_id=r.reserver_id,
            reserver_name=r.reserver_name,
            court_name=r.court_name or DEFAULT_COURT_NAME,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]

    return MonthlyReservationsOut(
        year=year,
        month=month,
        time_slots=VALID_TIME_SLOTS,
        reservations=reservations,
    )


@router.post("", response_model=ReservationOut)
async def create_reservation(
    req: CreateReservationRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """구장 예약 등록. 지난 날짜는 등록 불가."""
    try:
        target_date = datetime.strptime(req.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date 형식 오류 (YYYY-MM-DD)")

    today = date.today()
    if target_date < today:
        raise HTTPException(status_code=400, detail="지난 날짜에는 예약 등록할 수 없습니다.")

    if req.time_slot not in VALID_TIME_SLOTS:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 시간대입니다. (가능: {', '.join(VALID_TIME_SLOTS)})"
        )

    court_name = req.court_name.strip() if req.court_name else DEFAULT_COURT_NAME
    if not court_name:
        court_name = DEFAULT_COURT_NAME

    existing = db.query(CourtReservation).filter(
        CourtReservation.date == target_date,
        CourtReservation.time_slot == req.time_slot,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"이미 {existing.reserver_name}님이 {req.time_slot} 시간대를 예약했습니다."
        )

    new_res = CourtReservation(
        date=target_date,
        time_slot=req.time_slot,
        reserver_id=current_user.id,
        reserver_name=current_user.name,
        court_name=court_name,
    )
    db.add(new_res)
    try:
        db.commit()
        db.refresh(new_res)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="이미 예약된 시간대입니다.")

    return ReservationOut(
        id=new_res.id,
        date=new_res.date.isoformat(),
        time_slot=new_res.time_slot,
        reserver_id=new_res.reserver_id,
        reserver_name=new_res.reserver_name,
        court_name=new_res.court_name,
        created_at=new_res.created_at.isoformat() if new_res.created_at else "",
    )


@router.put("/{reservation_id}", response_model=ReservationOut)
async def update_reservation(
    reservation_id: int,
    req: UpdateReservationRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """구장 이름만 수정 가능. 본인 예약만."""
    res = db.query(CourtReservation).filter(CourtReservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="예약 정보를 찾을 수 없습니다.")

    if res.reserver_id != current_user.id:
        raise HTTPException(status_code=403, detail="본인의 예약만 수정할 수 있습니다.")

    if res.date < date.today():
        raise HTTPException(status_code=400, detail="지난 예약은 수정할 수 없습니다.")

    court_name = req.court_name.strip() if req.court_name else DEFAULT_COURT_NAME
    if not court_name:
        court_name = DEFAULT_COURT_NAME
    res.court_name = court_name
    db.commit()
    db.refresh(res)

    return ReservationOut(
        id=res.id,
        date=res.date.isoformat(),
        time_slot=res.time_slot,
        reserver_id=res.reserver_id,
        reserver_name=res.reserver_name,
        court_name=res.court_name,
        created_at=res.created_at.isoformat() if res.created_at else "",
    )


@router.delete("/{reservation_id}")
async def delete_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """예약 취소. 본인 + 시스템관리자만."""
    res = db.query(CourtReservation).filter(CourtReservation.id == reservation_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="예약 정보를 찾을 수 없습니다.")

    if res.reserver_id != current_user.id and not is_sys_admin(current_user):
        raise HTTPException(status_code=403, detail="본인의 예약만 취소할 수 있습니다.")

    if res.date < date.today():
        raise HTTPException(status_code=400, detail="지난 예약은 취소할 수 없습니다.")

    db.delete(res)
    db.commit()
    return {"message": "예약이 취소되었습니다.", "reservation_id": reservation_id}
