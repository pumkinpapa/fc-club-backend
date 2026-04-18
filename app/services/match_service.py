"""
경기/투표/팀편성 비즈니스 로직
"""

import random
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Match, MatchRecord, Member


# ──────────────────────────────────────────────
# 기존 함수들
# ──────────────────────────────────────────────

def get_next_match_date(match_day: int = 6) -> date:
    """다음 경기일(일요일) 계산"""
    today = date.today()
    days_ahead = match_day - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def get_or_create_match(db: Session, match_date: date) -> Match:
    """해당 날짜의 경기를 조회하거나 새로 생성"""
    match = db.query(Match).filter(Match.match_date == match_date).first()
    if not match:
        match = Match(match_date=match_date, status="투표중")
        db.add(match)
        db.commit()
        db.refresh(match)
    return match


def vote(db: Session, match_id: int, member_id: int, attendance: str) -> MatchRecord:
    """참석여부 투표"""
    record = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == member_id)
        .first()
    )
    if record:
        record.attendance = attendance
    else:
        record = MatchRecord(
            match_id=match_id,
            member_id=member_id,
            attendance=attendance,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_vote_status(db: Session, match: Match) -> dict:
    """투표 현황 조회"""
    records = db.query(MatchRecord).filter(MatchRecord.match_id == match.id).all()
    all_members = db.query(Member).all()

    voted_member_ids = {r.member_id for r in records}

    attendees = [r for r in records if r.attendance == "참석"]
    absentees = [r for r in records if r.attendance == "불참"]
    pending = [m for m in all_members if m.id not in voted_member_ids]

    return {
        "attendees": attendees,
        "absentees": absentees,
        "pending": pending,
    }


def assign_teams_and_duties(db: Session, match_id: int) -> dict:
    """
    팀 편성 및 역할 배정

    - 골대담당 2명, 음료담당 1명 랜덤 배정
    - 인원 수에 따라 2팀 또는 3팀 (21명 이상 시 3팀)
    """
    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    if len(records) < 3:
        raise ValueError("최소 3명 이상이 참석해야 팀 편성이 가능합니다.")

    shuffled = list(records)
    random.shuffle(shuffled)

    goal_keepers = shuffled[:2]
    drink_person = shuffled[2]

    for r in records:
        r.duty = ""
    for r in goal_keepers:
        r.duty = "골대"
    drink_person.duty = "음료" if drink_person.duty != "골대" else "음료, 골대"

    num_teams = 3 if len(records) >= 21 else 2
    for i, record in enumerate(shuffled):
        record.team = f"{(i % num_teams) + 1}팀"

    match = db.query(Match).filter(Match.id == match_id).first()
    match.status = "편성완료"

    db.commit()

    teams = {}
    duties = {"골대": [], "음료": []}
    for r in records:
        db.refresh(r)
        member = db.query(Member).filter(Member.id == r.member_id).first()
        team_name = r.team
        if team_name not in teams:
            teams[team_name] = []
        teams[team_name].append({
            "member_id": r.member_id,
            "name": member.name,
            "duty": r.duty,
        })
        if "골대" in r.duty:
            duties["골대"].append(member.name)
        if "음료" in r.duty:
            duties["음료"].append(member.name)

    return {"teams": teams, "duties": duties}


def record_result(db: Session, match_id: int, winning_team: str) -> Match:
    """
    경기 결과 기록
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 결과를 변경할 수 없습니다.")

    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    for record in records:
        if winning_team == "무승부":
            record.match_result = "무"
        elif record.team == winning_team:
            record.match_result = "승"
        else:
            record.match_result = "패"

    match.status = "경기완료"
    match.result_summary = (
        "무승부" if winning_team == "무승부" else f"{winning_team} 승리"
    )

    db.commit()
    db.refresh(match)
    return match


def get_rankings(db: Session) -> list[dict]:
    """누적 승점 랭킹 계산 (MatchRecord에서 실시간 집계)"""
    members = db.query(Member).all()
    stats = {}

    for member in members:
        records = (
            db.query(MatchRecord)
            .filter(
                MatchRecord.member_id == member.id,
                MatchRecord.attendance == "참석",
                MatchRecord.match_result != "",
            )
            .all()
        )

        wins = sum(1 for r in records if r.match_result == "승")
        draws = sum(1 for r in records if r.match_result == "무")
        losses = sum(1 for r in records if r.match_result == "패")
        played = wins + draws + losses
        points = wins * 3 + draws * 1

        if played > 0:
            stats[member.id] = {
                "member_id": member.id,
                "name": member.name,
                "played": played,
                "wins": wins,
                "draws": draws,
                "losses": losses,
                "points": points,
                "attendance_count": len(records),
            }

    ranked = sorted(
        stats.values(),
        key=lambda x: (x["points"], x["wins"]),
        reverse=True,
    )

    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return ranked


# ══════════════════════════════════════════════
# 팀/담당자/결과 수정
# ══════════════════════════════════════════════

def _parse_winning_team(match: Match) -> Optional[str]:
    """match.result_summary에서 승리팀 추출"""
    if not match.result_summary or match.result_summary == "무승부":
        return None
    return match.result_summary.replace(" 승리", "").strip()


def update_teams(db: Session, match_id: int, assignments: list[dict]) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 수정할 수 없습니다.")
    if match.status == "투표중":
        raise ValueError("먼저 팀 편성을 완료해주세요.")

    winning_team = _parse_winning_team(match)
    is_draw = match.result_summary == "무승부"
    result_recorded = match.status == "경기완료"

    for a in assignments:
        mid = a["member_id"]
        team = a["team"]
        record = (
            db.query(MatchRecord)
            .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == mid)
            .first()
        )
        if not record:
            record = MatchRecord(match_id=match_id, member_id=mid, attendance="참석")
            db.add(record)
        record.attendance = "참석"
        record.team = team
        if result_recorded:
            if is_draw:
                record.match_result = "무"
            elif winning_team and team == winning_team:
                record.match_result = "승"
            else:
                record.match_result = "패"

    db.commit()
    db.refresh(match)
    return match


def update_duties(db: Session, match_id: int, duties: list[dict]) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 수정할 수 없습니다.")
    if match.status == "투표중":
        raise ValueError("먼저 팀 편성을 완료해주세요.")

    for d in duties:
        record = (
            db.query(MatchRecord)
            .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == d["member_id"])
            .first()
        )
        if record:
            record.duty = d["duty"]

    db.commit()
    db.refresh(match)
    return match


def update_result_members(
    db: Session, match_id: int, additions: list[dict], removals: list[int]
) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 수정할 수 없습니다.")
    if match.status != "경기완료":
        raise ValueError("경기완료 상태에서만 결과 명단을 수정할 수 있습니다.")

    winning_team = _parse_winning_team(match)
    is_draw = match.result_summary == "무승부"

    for mid in removals:
        record = (
            db.query(MatchRecord)
            .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == mid)
            .first()
        )
        if record:
            record.attendance = "불참"
            record.team = ""
            record.match_result = ""
            record.duty = ""

    for a in additions:
        mid = a["member_id"]
        team = a["team"]
        record = (
            db.query(MatchRecord)
            .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == mid)
            .first()
        )
        if not record:
            record = MatchRecord(match_id=match_id, member_id=mid, attendance="참석")
            db.add(record)
        record.attendance = "참석"
        record.team = team
        if is_draw:
            record.match_result = "무"
        elif winning_team and team == winning_team:
            record.match_result = "승"
        else:
            record.match_result = "패"

    db.commit()
    db.refresh(match)
    return match


def confirm_result(db: Session, match_id: int) -> Match:
    """
    결과 확정 (경기완료 → 확정완료)

    ★ 확정과 동시에 다음 주 일요일 경기를 자동 생성하여 투표 즉시 시작!
       이전에는 매주 수요일에 스케줄러가 투표를 열었지만, 이제는 확정 시점에 바로 다음 경기가 열림.
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status != "경기완료":
        raise ValueError("경기완료 상태에서만 확정할 수 있습니다.")

    match.status = "확정완료"

    # ★ 다음 주 일요일 경기 자동 생성 (7일 후)
    next_date = match.match_date + timedelta(days=7)
    existing_next = db.query(Match).filter(Match.match_date == next_date).first()
    if not existing_next:
        next_match = Match(match_date=next_date, status="투표중")
        db.add(next_match)

    db.commit()
    db.refresh(match)
    return match


def cancel_confirm(db: Session, match_id: int) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status != "확정완료":
        raise ValueError("확정완료 상태가 아닙니다.")
    match.status = "경기완료"
    db.commit()
    db.refresh(match)
    return match


def cancel_assignment(db: Session, match_id: int) -> Match:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 편성 취소할 수 없습니다. 먼저 확정을 취소하세요.")

    records = db.query(MatchRecord).filter(MatchRecord.match_id == match_id).all()
    for r in records:
        r.team = ""
        r.duty = ""
        r.match_result = ""

    match.status = "투표중"
    match.result_summary = None
    db.commit()
    db.refresh(match)
    return match


# ══════════════════════════════════════════════
# ★★★ 신규: 경기/회원 완전 삭제 (시스템관리자) ★★★
# ══════════════════════════════════════════════

def delete_match(db: Session, match_id: int) -> None:
    """
    경기 완전 삭제 (시스템관리자 전용)

    - Match 레코드 삭제
    - 관련 MatchRecord(투표/팀/결과) 모두 삭제
    - 이후 /api/matches/next 호출 시 새 경기가 자동 생성됨 (투표중 상태)
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

    db.query(MatchRecord).filter(MatchRecord.match_id == match_id).delete(
        synchronize_session=False
    )
    db.delete(match)
    db.commit()


def delete_member_cascade(db: Session, member_id: int) -> str:
    """
    회원 완전 삭제 + 경기 기록 cascade 삭제 (시스템관리자 전용)

    returns: 삭제된 회원 이름
    """
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise ValueError("회원을 찾을 수 없습니다.")

    if member.phone == "01000000001":
        raise ValueError("시스템관리자 계정은 삭제할 수 없습니다.")

    name = member.name

    db.query(MatchRecord).filter(MatchRecord.member_id == member_id).delete(
        synchronize_session=False
    )
    db.delete(member)
    db.commit()
    return name
