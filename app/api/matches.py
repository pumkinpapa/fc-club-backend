"""
경기 / 투표 / 팀 편성 / 결과 기록 API
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
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
    update_teams, update_duties, update_result_members,
    confirm_result, cancel_confirm, cancel_assignment,
    delete_match,
    set_vote_for_member,
    record_three_team_result,  # ★ 신규: 3팀 경기
    update_match_date,  # ★ 신규: 경기 날짜 변경
    THREE_TEAM_MARKER,
)
from app.services.solapi_service import send_alimtalk_bulk

settings = get_settings()

router = APIRouter(prefix="/api/matches", tags=["경기관리"])


# 시스템관리자 전화번호
SYS_ADMIN_PHONE = "01000000001"


def get_system_admin_user(current_user: Member = Depends(get_current_user)) -> Member:
    """시스템관리자 권한 확인"""
    if current_user.phone != SYS_ADMIN_PHONE:
        raise HTTPException(status_code=403, detail="시스템관리자만 수행 가능합니다.")
    return current_user


# ──────────────────────────────────
# 경기 조회
# ──────────────────────────────────

@router.get("/", response_model=List[MatchResponse])
async def list_matches(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
):
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
    match_date = get_next_match_date(settings.match_day_of_week)
    match = get_or_create_match(db, match_date)
    return MatchResponse.model_validate(match)


@router.get("/{match_id}", response_model=MatchResponse)
async def get_match(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
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
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    status = get_vote_status(db, match)

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
    num_teams: Optional[int] = Query(None, description="2 또는 3 (미지정 시 자동)"),
):
    """팀 편성 및 역할 배정 (관리자 전용)
    - num_teams 쿼리 파라미터로 2팀/3팀 선택 가능
    - 미지정 시 18명 이상이면 3팀, 그 외 2팀 자동
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="경기를 찾을 수 없습니다.")

    try:
        result = assign_teams_and_duties(db, match_id, num_teams=num_teams)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"{result.get('num_teams',2)}팀 편성이 완료되었습니다.",
        "teams": result["teams"],
        "duties": result["duties"],
        "num_teams": result.get("num_teams", 2),
    }


@router.post("/{match_id}/notify-teams")
async def notify_teams(
    match_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
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
    try:
        match = record_result(db, match_id, req.winning_team)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"경기 결과가 기록되었습니다: {match.result_summary}",
        "match": MatchResponse.model_validate(match),
    }


# ★★★ 신규: 3팀 경기 결과 입력 ★★★
class ThreeTeamResultRequest(BaseModel):
    rankings: dict  # {"1팀": 1, "2팀": 3, "3팀": 2} 형식


@router.post("/{match_id}/result-3team")
async def submit_three_team_result(
    match_id: int,
    req: ThreeTeamResultRequest,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """3팀 경기 결과 기록 (관리자 전용)"""
    # rankings의 값이 int인지 검증
    rankings = {}
    try:
        for team, rank in req.rankings.items():
            rankings[str(team)] = int(rank)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="순위는 1, 2, 3 숫자여야 합니다.")

    try:
        match = record_three_team_result(db, match_id, rankings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"3팀 경기 결과가 기록되었습니다",
        "match": MatchResponse.model_validate(match),
    }


@router.get("/{match_id}/records", response_model=List[MatchRecordResponse])
async def get_match_records(
    match_id: int,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
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


# ══════════════════════════════════════════════
# ★★★ 신규: 전체 경기 기록 조회 (결과탭 이력용) ★★★
# ══════════════════════════════════════════════

@router.get("/history/all")
async def get_all_match_history(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    모든 경기 + 각 경기별 참여 기록을 한 번에 조회 (결과탭 전체 이력용)

    - 경기일 내림차순 정렬
    - 투표중 상태 포함
    - 각 경기마다 attendees(참석자) 리스트 포함
    """
    matches = (
        db.query(Match)
        .order_by(Match.match_date.desc())
        .all()
    )

    # 모든 회원을 한 번에 조회해 캐시 (N+1 쿼리 방지)
    members = {m.id: m for m in db.query(Member).all()}

    result = []
    for match in matches:
        records = (
            db.query(MatchRecord)
            .filter(
                MatchRecord.match_id == match.id,
                MatchRecord.attendance == "참석",
            )
            .all()
        )

        attendees = []
        for r in records:
            member = members.get(r.member_id)
            if not member:
                continue
            attendees.append({
                "member_id": r.member_id,
                "member_name": member.name,
                "member_birth": member.birth,
                "team": r.team or "",
                "duty": r.duty or "",
                "match_result": r.match_result or "",
            })

        result.append({
            "id": match.id,
            "match_date": match.match_date.isoformat() if match.match_date else None,
            "status": match.status,
            "result_summary": match.result_summary,
            "attendees": attendees,
            "attendee_count": len(attendees),
        })

    return {"matches": result, "total": len(result)}


# ══════════════════════════════════════════════
# 팀/담당자/결과 수정 API
# ══════════════════════════════════════════════

class TeamAssignmentItem(BaseModel):
    member_id: int
    team: str


class TeamUpdateRequest(BaseModel):
    assignments: List[TeamAssignmentItem]


class DutyItem(BaseModel):
    member_id: int
    duty: str


class DutyUpdateRequest(BaseModel):
    duties: List[DutyItem]


class ResultMemberUpdateRequest(BaseModel):
    additions: List[TeamAssignmentItem] = []
    removals: List[int] = []


@router.put("/{match_id}/teams")
async def update_match_teams(
    match_id: int,
    req: TeamUpdateRequest,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    try:
        match = update_teams(
            db, match_id, [a.model_dump() for a in req.assignments]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "팀 편성이 저장되었습니다.", "match": MatchResponse.model_validate(match)}


@router.put("/{match_id}/duties")
async def update_match_duties(
    match_id: int,
    req: DutyUpdateRequest,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    try:
        update_duties(db, match_id, [d.model_dump() for d in req.duties])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "담당자가 저장되었습니다."}


@router.put("/{match_id}/result-members")
async def update_match_result_members(
    match_id: int,
    req: ResultMemberUpdateRequest,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    try:
        update_result_members(
            db, match_id,
            [a.model_dump() for a in req.additions],
            req.removals,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "결과가 수정되었습니다."}


@router.post("/{match_id}/confirm")
async def confirm_match_result(
    match_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """경기결과 확정 (관리자 전용). 확정 즉시 다음 주 경기 자동 생성 → 투표 시작."""
    try:
        match = confirm_result(db, match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": "경기 결과가 확정되었습니다. 다음 주 경기 투표가 시작되었습니다.",
        "match": MatchResponse.model_validate(match),
    }


@router.post("/{match_id}/cancel-confirm")
async def cancel_match_confirm(
    match_id: int,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    try:
        match = cancel_confirm(db, match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "확정이 취소되었습니다.", "match": MatchResponse.model_validate(match)}


@router.post("/{match_id}/cancel-assign")
async def cancel_match_assignment(
    match_id: int,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    try:
        match = cancel_assignment(db, match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "편성이 취소되었습니다.", "match": MatchResponse.model_validate(match)}


# ══════════════════════════════════════════════
# ★★★ 신규: 경기 완전 삭제 (시스템관리자) ★★★
# ══════════════════════════════════════════════

@router.delete("/{match_id}")
async def delete_match_endpoint(
    match_id: int,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    """
    경기 완전 삭제 (시스템관리자 전용)
    """
    try:
        delete_match(db, match_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": "경기가 삭제되었습니다."}


# ══════════════════════════════════════════════
# ★★★ 신규: 경기 날짜 변경 (관리자) ★★★
# ══════════════════════════════════════════════

class UpdateMatchDateRequest(BaseModel):
    new_date: str  # ISO 형식 "2026-05-03"


@router.put("/{match_id}/date")
async def change_match_date(
    match_id: int,
    req: UpdateMatchDateRequest,
    db: Session = Depends(get_db),
    admin: Member = Depends(get_admin_user),
):
    """
    경기 날짜 변경 (관리자 전용)

    - new_date: "YYYY-MM-DD" 형식
    - 과거 날짜로 변경 불가
    - 확정완료된 경기는 변경 불가
    - 같은 날짜에 다른 경기가 이미 있으면 거부
    - 투표/팀편성/결과 데이터는 모두 유지됨
    """
    try:
        new_date = date.fromisoformat(req.new_date)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail="날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)",
        )

    try:
        match = update_match_date(db, match_id, new_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "message": f"경기 날짜가 {new_date.isoformat()}로 변경되었습니다.",
        "match": MatchResponse.model_validate(match),
    }


# ══════════════════════════════════════════════
# ★★★ 신규: 시스템관리자의 대리 투표 변경 ★★★
# ══════════════════════════════════════════════

class SetVoteRequest(BaseModel):
    member_id: int
    attendance: str  # "참석" | "불참" | "미응답"


@router.put("/{match_id}/set-vote")
async def set_vote_endpoint(
    match_id: int,
    req: SetVoteRequest,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    """
    시스템관리자가 특정 회원의 투표 상태를 대신 변경 (드래그앤드롭 UI용)

    - attendance: "참석" / "불참" / "미응답"
    - "미응답"이면 MatchRecord 삭제 (투표 초기화)
    - 확정완료된 경기는 변경 불가
    """
    try:
        set_vote_for_member(db, match_id, req.member_id, req.attendance)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": f"투표가 '{req.attendance}'(으)로 변경되었습니다."}


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


# ══════════════════════════════════════════════
# ★★★ DB 마이그레이션 (시스템관리자) ★★★
# ══════════════════════════════════════════════

class MigrateRequest(BaseModel):
    target_url: str
    wipe_target: bool = False  # True면 대상 DB의 기존 데이터 모두 삭제 후 이전


@router.post("/migrate-to-new-db")
async def migrate_to_new_db(
    req: MigrateRequest,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    """
    현재 DB의 모든 데이터를 다른 PostgreSQL DB로 복사 (시스템관리자 전용)

    - target_url: 대상 DB의 PostgreSQL connection string (예: Neon URL)
    - wipe_target: True면 대상 DB의 기존 데이터 삭제 후 이전
    - 현재 DB는 변경되지 않음 (읽기만 함)
    - 이전 후 Render 대시보드에서 DATABASE_URL을 target_url로 변경해야 함
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    target_url = req.target_url.strip()
    # postgres:// → postgresql:// (SQLAlchemy 요구사항)
    if target_url.startswith("postgres://"):
        target_url = "postgresql://" + target_url[len("postgres://"):]
    if not target_url.startswith("postgresql://"):
        raise HTTPException(
            status_code=400,
            detail="올바른 PostgreSQL URL이 아닙니다. (postgresql:// 또는 postgres://로 시작해야 함)"
        )

    # 현재 DB 데이터 모두 읽기
    members = db.query(Member).all()
    matches = db.query(Match).all()
    records = db.query(MatchRecord).all()

    # 모델 객체를 dict로 변환 (세션 분리 후에도 접근 가능하도록)
    def to_dict(obj):
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

    members_data = [to_dict(m) for m in members]
    matches_data = [to_dict(m) for m in matches]
    records_data = [to_dict(r) for r in records]

    # 대상 DB 연결 및 테이블 생성
    try:
        target_engine = create_engine(target_url, pool_pre_ping=True)
        # Member.metadata는 모든 테이블 메타데이터 포함
        Member.metadata.create_all(bind=target_engine)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"대상 DB 연결 실패: {str(e)[:200]}"
        )

    TargetSession = sessionmaker(bind=target_engine, autocommit=False, autoflush=False)
    target_db = TargetSession()

    try:
        # 기존 데이터 확인
        existing_members = target_db.query(Member).count()
        existing_matches = target_db.query(Match).count()
        existing_records = target_db.query(MatchRecord).count()
        existing_total = existing_members + existing_matches + existing_records

        if existing_total > 0:
            if not req.wipe_target:
                raise HTTPException(
                    status_code=400,
                    detail=f"대상 DB에 이미 데이터가 있습니다 (회원 {existing_members}, 경기 {existing_matches}, 기록 {existing_records}). wipe_target=true로 다시 시도하세요."
                )
            # 기존 데이터 삭제
            target_db.query(MatchRecord).delete()
            target_db.query(Match).delete()
            target_db.query(Member).delete()
            target_db.commit()

        # 데이터 복사 (ID 보존)
        for m in members_data:
            target_db.add(Member(**m))
        target_db.commit()

        for m in matches_data:
            target_db.add(Match(**m))
        target_db.commit()

        for r in records_data:
            target_db.add(MatchRecord(**r))
        target_db.commit()

        # Auto-increment 시퀀스 재설정 (다음 INSERT 시 충돌 방지)
        for cls in [Member, Match, MatchRecord]:
            tbl = cls.__tablename__
            target_db.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tbl}), 1), "
                f"(SELECT MAX(id) FROM {tbl}) IS NOT NULL);"
            ))
        target_db.commit()

    except HTTPException:
        raise
    except Exception as e:
        target_db.rollback()
        raise HTTPException(status_code=500, detail=f"이전 실패: {str(e)[:300]}")
    finally:
        target_db.close()
        target_engine.dispose()

    return {
        "message": "데이터 이전이 완료되었습니다.",
        "members": len(members_data),
        "matches": len(matches_data),
        "match_records": len(records_data),
        "next_step": "Render 대시보드에서 DATABASE_URL을 새 URL로 변경하고 저장하세요.",
    }


# ══════════════════════════════════════════════
# ★★★ 엑셀 과거 경기 기록 일괄 Import (시스템관리자) ★★★
# ══════════════════════════════════════════════

class ImportMatchItem(BaseModel):
    date: str  # "2026-01-04" 형식
    summary: str  # "1팀 승리", "무승부", "[3팀] 1위:1팀 2위:2팀 3위:3팀"
    records: List[List[str]]  # [["김철수", "승"], ...]
    num_teams: int = 2  # 2 또는 3 (3이면 3팀 경기)


class ImportMatchesRequest(BaseModel):
    matches: List[ImportMatchItem]
    skip_existing: bool = True


@router.post("/import-history")
async def import_match_history(
    req: ImportMatchesRequest,
    db: Session = Depends(get_db),
    sys_admin: Member = Depends(get_system_admin_user),
):
    """
    과거 경기 기록 일괄 import (시스템관리자 전용)
    - 이름으로 회원 매핑, 없는 회원은 건너뜀
    - num_teams=3이면 3팀 경기로 저장
    """
    from datetime import datetime

    members_by_name = {m.name: m.id for m in db.query(Member).all()}

    created_matches = 0
    skipped_matches = 0
    total_records = 0
    skipped_names = set()

    for item in req.matches:
        try:
            match_date = datetime.strptime(item.date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"잘못된 날짜 형식: {item.date}")

        existing = db.query(Match).filter(Match.match_date == match_date).first()
        if existing:
            if req.skip_existing:
                skipped_matches += 1
                continue
            else:
                db.query(MatchRecord).filter(MatchRecord.match_id == existing.id).delete(
                    synchronize_session=False
                )
                db.delete(existing)
                db.commit()

        is_three = item.num_teams == 3

        # result_summary 조정
        if is_three and not item.summary.startswith(THREE_TEAM_MARKER):
            summary = f"{THREE_TEAM_MARKER} 1위:1팀 2위:2팀 3위:3팀"
        else:
            summary = item.summary

        match = Match(
            match_date=match_date,
            status="확정완료",
            result_summary=summary,
        )
        db.add(match)
        db.commit()
        db.refresh(match)

        for name, result in item.records:
            mid = members_by_name.get(name)
            if mid is None:
                skipped_names.add(name)
                continue

            if is_three:
                # 3팀: 승=1팀, 무=2팀, 패=3팀
                if result == "승":
                    team = "1팀"
                elif result == "무":
                    team = "2팀"
                else:
                    team = "3팀"
            else:
                # 2팀
                if result == "승":
                    team = "1팀"
                elif result == "패":
                    team = "2팀"
                else:
                    team = "1팀"

            record = MatchRecord(
                match_id=match.id,
                member_id=mid,
                attendance="참석",
                team=team,
                duty="",
                match_result=result,
            )
            db.add(record)
            total_records += 1

        db.commit()
        created_matches += 1

    return {
        "message": "과거 경기 기록 import 완료",
        "created_matches": created_matches,
        "skipped_matches": skipped_matches,
        "total_records": total_records,
        "skipped_members": sorted(list(skipped_names)),
    }
