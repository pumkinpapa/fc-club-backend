"""
⚙️ 경기 설정 API - 경기 시간 / 경기장 정보 수정
- PUT /api/matches/{id}/settings  -> 경기 설정 수정 (관리자)

별도 파일로 분리하여 기존 matches.py에 영향 없도록 함.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Member, Match

router = APIRouter(prefix="/api/matches", tags=["경기설정"])

SYS_ADMIN_PHONE = "01000000001"


def is_admin_user(user: Member) -> bool:
    """관리자 or 시스템관리자"""
    if user.phone == SYS_ADMIN_PHONE:
        return True
    if user.role in ("회장", "관리자", "총무"):
        return True
    return False


class MatchSettingsRequest(BaseModel):
    match_time: Optional[str] = Field(default=None, description="HH:MM 형식")
    venue_name: Optional[str] = Field(default=None, max_length=100)
    venue_lat: Optional[float] = None
    venue_lng: Optional[float] = None
    venue_radius: Optional[int] = Field(default=None, ge=10, le=5000)


@router.put("/{match_id}/settings")
async def update_match_settings(
    match_id: int,
    req: MatchSettingsRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """경기 설정 수정 (관리자만) - 시간, 장소, 반경 등"""
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="관리자만 수정할 수 있습니다.")

    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    # 시간 형식 검증
    if req.match_time is not None:
        try:
            parts = req.match_time.split(":")
            if len(parts) != 2:
                raise ValueError()
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError()
            match.match_time = f"{hour:02d}:{minute:02d}"
        except Exception:
            raise HTTPException(status_code=400, detail="match_time 형식 오류 (HH:MM)")

    if req.venue_name is not None:
        name = req.venue_name.strip() or "서울숲"
        match.venue_name = name

    if req.venue_lat is not None:
        if not (-90 <= req.venue_lat <= 90):
            raise HTTPException(status_code=400, detail="위도 범위 오류")
        match.venue_lat = req.venue_lat

    if req.venue_lng is not None:
        if not (-180 <= req.venue_lng <= 180):
            raise HTTPException(status_code=400, detail="경도 범위 오류")
        match.venue_lng = req.venue_lng

    if req.venue_radius is not None:
        match.venue_radius = req.venue_radius

    db.commit()
    db.refresh(match)
    return {
        "message": "경기 설정이 업데이트되었습니다.",
        "match_id": match.id,
        "match_time": match.match_time,
        "venue_name": match.venue_name,
        "venue_lat": match.venue_lat,
        "venue_lng": match.venue_lng,
        "venue_radius": match.venue_radius,
    }
