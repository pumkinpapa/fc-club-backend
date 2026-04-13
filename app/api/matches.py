"""
경기 / 투표 / 팀 편성 / 결과 기록 API
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user, get_admin_user
from app.models import Member, Match, MatchRecord
from app.schemas import (
    MatchResponse, VoteRequest, VoteStatusResponse,
    MatchRecordResponse, MemberResponse,
    TeamAssignmentResponse, ResultRequest,
)
from app.services.match_service import (
    get_next_match_date, get_or_create_match, vote,
    get_vote_status, assign_teams_and_duties, record_result,
)
from app.services.solapi_service import send_alimtalk_bulk

settings = get_settings()

router = APIRouter(prefix="/api/matches", tags=["경기관리"])


# ──────────────────────────────────
# 경기 조회
# ──────────────────────────────────

@router.get("/", response_model=List[MatchResponse])
async def list_matches(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
):
    """경기 목록 조회 (최신순)"""
    matches = (
        db.query(Match)
        .order_by(Match.match_date.desc())
        .limit(limit)
        .all()
    )
    return [MatchResponse.model_validate(m) for m in matches]


@router.get("/next", response_model=MatchResponse)
async def get_next_match(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """다음 경기 정보 조회 (없으면 자동 생성)"""
    match_date = get_next_match_date(settings.match_day_of_week)
    match = get_or_create_match(db, match_date)
    return MatchResponse.model_validate(match)


@router.get("/{match_id}", response_model=MatchResponse)
async def get_match(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """경기 상세 조회"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")
    return MatchResponse.model_validate(match)


# ──────────────────────────────────
# 투표
# ──────────────────────────────────

@router.post("/{match_id}/vote")
async def submit_vote(
    match_id: int,
    req: VoteRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """참석여부 투표"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    if req.attendance not in ("참석", "불참"):
        raise HTTPException(status_code=400, detail="참석 또는 불참만 선택 가능합니다.")

    record = vote(db, match_id, current_user.id, req.attendance)
    return {
        "message": f"{req.attendance}으로 투표되었습니다.",
        "record_id": record.id,
    }


@router.get("/{match_id}/votes", response_model=VoteStatusResponse)
async def get_votes(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """투표 현황 조회"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    status = get_vote_status(db, match)

    # 내 투표 확인
    my_record = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == current_user.id)
        .first()
    )

    def record_to_response(r: MatchRecord) -> MatchRecordResponse:
        member = db.query(Member).filter(Member.id == r.member_id).first()
        return MatchRecordResponse(
            id=r.id,
            match_id=r.match_id,
            member_id=r.member_id,
            member_name=member.name if member else "",
            member_birth=member.birth if member else "",
            attendance=r.attendance,
            duty=r.duty,
            team=r.team,
            match_result=r.match_result,
        )

    return VoteStatusResponse(
        match=MatchResponse.model_validate(match),
        attendees=[record_to_response(r) for r in status["attendees"]],
        absentees=[record_to_response(r) for r in status["absentees"]],
        pending=[MemberResponse.model_validate(m) for m in status["pending"]],
        my_vote=my_record.attendance if my_record else None,
    )


# ──────────────────────────────────
# 팀/역할 편성
# ──────────────────────────────────

@router.post("/{match_id}/assign-teams")
async def assign_teams(
    match_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """팀 편성 및 역할 배정 (관리자 전용)"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    try:
        result = assign_teams_and_duties(db, match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "팀 편성이 완료되었습니다.",
        "teams": result["teams"],
        "duties": result["duties"],
    }


@router.post("/{match_id}/notify-teams")
async def notify_teams(
    match_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """편성 결과 알림톡 발송 (관리자 전용)"""
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    recipients = []
    for record in records:
        member = db.query(Member).filter(Member.id == record.member_id).first()
        if member and member.phone:
            duty_text = f"담당: {record.duty}" if record.duty else ""
            recipients.append({
                "to": member.phone,
                "variables": {
                    "#{이름}": member.name,
                    "#{경기일}": match.match_date.strftime("%m월 %d일"),
                    "#{팀}": record.team,
                    "#{담당}": duty_text,
                },
            })

    if recipients:
        result = await send_alimtalk_bulk(
            recipients=recipients,
            template_id=settings.solapi_template_result,
        )
        return {"message": f"{len(recipients)}명에게 알림톡 발송 완료", "result": result}

    return {"message": "발송 대상이 없습니다."}


# ──────────────────────────────────
# 경기 결과
# ──────────────────────────────────

@router.post("/{match_id}/result")
async def submit_result(
    match_id: int,
    req: ResultRequest,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """경기 결과 입력 (관리자 전용)"""
    try:
        match = record_result(db, match_id, req.winning_team)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"경기 결과가 기록되었습니다: {match.result_summary}",
        "match": MatchResponse.model_validate(match),
    }


@router.get("/{match_id}/records", response_model=List[MatchRecordResponse])
async def get_match_records(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """경기 참여 기록 조회"""
    records = db.query(MatchRecord).filter(MatchRecord.match_id == match_id).all()

    result = []
    for r in records:
        member = db.query(Member).filter(Member.id == r.member_id).first()
        result.append(MatchRecordResponse(
            id=r.id,
            match_id=r.match_id,
            member_id=r.member_id,
            member_name=member.name if member else "",
            member_birth=member.birth if member else "",
            attendance=r.attendance,
            duty=r.duty,
            team=r.team,
            match_result=r.match_result,
        ))
    return result


# ──────────────────────────────────
# 수동 알림톡 발송 (테스트용)
# ──────────────────────────────────

@router.post("/send-vote-notification")
async def send_vote_notification_manual(
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """수동으로 투표 알림톡 발송 (관리자 전용, 테스트용)"""
    from app.services.scheduler import send_vote_notifications
    await send_vote_notifications()
    return {"message": "투표 알림톡이 발송되었습니다."}
