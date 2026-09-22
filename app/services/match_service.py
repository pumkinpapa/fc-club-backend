"""
경기/투표/팀편성 비즈니스 로직
"""

import random
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Match, MatchRecord, Member


# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────

THREE_TEAM_THRESHOLD = 18  # 18명 이상이면 3팀으로 편성
THREE_TEAM_MARKER = "[3팀]"  # result_summary에 이 접두사가 있으면 3팀 경기


def is_three_team_match(match: Match) -> bool:
    """Match가 3팀 경기인지 판별 (result_summary 기반)"""
    return bool(match.result_summary and match.result_summary.startswith(THREE_TEAM_MARKER))


# ──────────────────────────────────────────────
# 기존 함수들
# ──────────────────────────────────────────────

def get_next_match_date(match_day: int = 6) -> date:
    today = date.today()
    days_ahead = match_day - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return today + timedelta(days=days_ahead)


def get_or_create_match(db: Session, match_date: date) -> Match:
    match = db.query(Match).filter(Match.match_date == match_date).first()
    if not match:
        match = Match(match_date=match_date, status="투표중")
        db.add(match)
        db.commit()
        db.refresh(match)
    return match


def vote(db: Session, match_id: int, member_id: int, attendance: str) -> MatchRecord:
    record = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.member_id == member_id)
        .first()
    )
    if record:
        record.attendance = attendance
    else:
        record = MatchRecord(match_id=match_id, member_id=member_id, attendance=attendance)
        db.add(record)
    db.commit()
    db.refresh(record)
    return record


def set_vote_for_member(
    db: Session, match_id: int, member_id: int, attendance: str
) -> Optional[MatchRecord]:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 투표를 변경할 수 없습니다.")

    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise ValueError("회원을 찾을 수 없습니다.")
    if member.status != "승인":
        raise ValueError("승인된 회원만 투표 대상입니다.")

    if attendance in ("미응답", "", None):
        db.query(MatchRecord).filter(
            MatchRecord.match_id == match_id,
            MatchRecord.member_id == member_id,
        ).delete(synchronize_session=False)
        db.commit()
        return None

    if attendance not in ("참석", "불참"):
        raise ValueError("참석, 불참, 미응답 중 하나여야 합니다.")

    return vote(db, match_id, member_id, attendance)


def get_vote_status(db: Session, match: Match) -> dict:
    """투표 현황 조회 (승인된 회원만 대상)"""
    records = db.query(MatchRecord).filter(MatchRecord.match_id == match.id).all()
    all_members = db.query(Member).filter(Member.status == "승인").all()

    voted_member_ids = {r.member_id for r in records}

    attendees = [r for r in records if r.attendance == "참석"]
    absentees = [r for r in records if r.attendance == "불참"]
    pending = [m for m in all_members if m.id not in voted_member_ids]

    return {"attendees": attendees, "absentees": absentees, "pending": pending}


def assign_teams_and_duties(db: Session, match_id: int, num_teams: int = None) -> dict:
    """
    팀 편성 및 역할 배정
    - num_teams: 2 또는 3 (관리자가 선택)
    - num_teams가 None이면 자동: 18명 이상이면 3팀, 그 외는 2팀
    """
    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    if len(records) < 3:
        raise ValueError("최소 3명 이상이 참석해야 팀 편성이 가능합니다.")

    # num_teams 결정
    if num_teams is None:
        num_teams = 3 if len(records) >= THREE_TEAM_THRESHOLD else 2
    elif num_teams not in (2, 3):
        raise ValueError("팀 수는 2 또는 3이어야 합니다.")
    elif num_teams == 3 and len(records) < 3:
        raise ValueError("3팀 편성은 최소 3명이 필요합니다.")

    shuffled = list(records)
    random.shuffle(shuffled)

    goal_keepers = shuffled[:2]
    drink_person = shuffled[2]

    for r in records:
        r.duty = ""
    for r in goal_keepers:
        r.duty = "골대"
    drink_person.duty = "음료" if drink_person.duty != "골대" else "음료, 골대"

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
        teams[team_name].append({"member_id": r.member_id, "name": member.name, "duty": r.duty})
        if "골대" in r.duty:
            duties["골대"].append(member.name)
        if "음료" in r.duty:
            duties["음료"].append(member.name)

    return {"teams": teams, "duties": duties, "num_teams": num_teams}


def record_result(db: Session, match_id: int, winning_team: str) -> Match:
    """경기 결과 기록 (2팀 경기용)"""
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

    # 3팀 경기 방지
    teams_present = set(r.team for r in records if r.team)
    if len(teams_present) >= 3:
        raise ValueError("3팀 경기는 3팀 결과 입력을 사용해주세요.")

    for record in records:
        if winning_team == "무승부":
            record.match_result = "무"
        elif record.team == winning_team:
            record.match_result = "승"
        else:
            record.match_result = "패"

    match.status = "경기완료"
    match.result_summary = "무승부" if winning_team == "무승부" else f"{winning_team} 승리"

    db.commit()
    db.refresh(match)
    return match


def record_three_team_result(db: Session, match_id: int, rankings: dict) -> Match:
    """
    3팀 경기 결과 기록

    rankings: {"1팀": 1, "2팀": 3, "3팀": 2} 형식
    - 1위팀 멤버 → match_result="승"
    - 2위팀 멤버 → match_result="무"
    - 3위팀 멤버 → match_result="패"
    result_summary: "[3팀] 1위:1팀 2위:3팀 3위:2팀"
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 결과를 변경할 수 없습니다.")

    if not isinstance(rankings, dict):
        raise ValueError("rankings는 {팀:순위} 형식이어야 합니다.")

    expected_teams = {"1팀", "2팀", "3팀"}
    if set(rankings.keys()) != expected_teams:
        raise ValueError(f"3팀 모두({expected_teams})의 순위를 지정해야 합니다.")

    if sorted(rankings.values()) != [1, 2, 3]:
        raise ValueError("순위는 1, 2, 3이 각각 한 번씩이어야 합니다.")

    rank_to_result = {1: "승", 2: "무", 3: "패"}

    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    for record in records:
        team_rank = rankings.get(record.team)
        if team_rank is None:
            record.match_result = ""
        else:
            record.match_result = rank_to_result[team_rank]

    match.status = "경기완료"
    team_by_rank = {v: k for k, v in rankings.items()}
    match.result_summary = (
        f"{THREE_TEAM_MARKER} 1위:{team_by_rank[1]} 2위:{team_by_rank[2]} 3위:{team_by_rank[3]}"
    )

    db.commit()
    db.refresh(match)
    return match


def get_rankings(db: Session) -> list[dict]:
    """
    누적 승점 랭킹 계산

    2팀 경기: 승=3점, 무=1점, 패=0점
    3팀 경기: 1위(승)=3점, 2위(무)=1점, 3위(패)=0점
    """
    members = db.query(Member).all()
    matches_map = {m.id: m for m in db.query(Match).all()}

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

        wins = 0
        draws = 0
        losses = 0
        points = 0

        for r in records:
            match = matches_map.get(r.match_id)
            three_team = match and is_three_team_match(match)

            if r.match_result == "승":
                wins += 1
                points += 3
            elif r.match_result == "무":
                draws += 1
                # 2팀 무승부 = 1점, 3팀 2위 = 1점 (동일)
                points += 1
            elif r.match_result == "패":
                losses += 1
                # 2팀 패배 = 0점, 3팀 3위 = 0점 (동일)
                points += 0

        played = wins + draws + losses

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

    ranked = sorted(stats.values(), key=lambda x: (x["points"], x["wins"]), reverse=True)

    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return ranked


# ══════════════════════════════════════════════
# 팀/담당자/결과 수정
# ══════════════════════════════════════════════

def _parse_winning_team(match: Match) -> Optional[str]:
    """승리팀(1위) 추출 - 2팀/3팀 공용"""
    if not match.result_summary or match.result_summary == "무승부":
        return None
    if is_three_team_match(match):
        try:
            after = match.result_summary.split("1위:")[1]
            return after.split(" ")[0]
        except (IndexError, AttributeError):
            return None
    return match.result_summary.replace(" 승리", "").strip()


def _get_three_team_rankings(match: Match) -> Optional[dict]:
    """3팀 경기의 {팀: 순위} 딕셔너리 반환"""
    if not is_three_team_match(match):
        return None
    result = {}
    for rank_num in (1, 2, 3):
        try:
            after = match.result_summary.split(f"{rank_num}위:")[1]
            team = after.split(" ")[0]
            result[team] = rank_num
        except (IndexError, AttributeError):
            return None
    return result


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
    three_team = is_three_team_match(match)
    three_rankings = _get_three_team_rankings(match) if three_team else None
    rank_to_result = {1: "승", 2: "무", 3: "패"}

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
            if three_team and three_rankings:
                team_rank = three_rankings.get(team)
                record.match_result = rank_to_result.get(team_rank, "") if team_rank else ""
            elif is_draw:
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
    three_team = is_three_team_match(match)
    three_rankings = _get_three_team_rankings(match) if three_team else None
    rank_to_result = {1: "승", 2: "무", 3: "패"}

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
        if three_team and three_rankings:
            team_rank = three_rankings.get(team)
            record.match_result = rank_to_result.get(team_rank, "") if team_rank else ""
        elif is_draw:
            record.match_result = "무"
        elif winning_team and team == winning_team:
            record.match_result = "승"
        else:
            record.match_result = "패"

    db.commit()
    db.refresh(match)
    return match


def get_next_sunday_from_date(from_date: date) -> date:
    """주어진 날짜 이후의 가장 빠른 일요일 반환 (from_date가 일요일이면 다음 일요일)"""
    # Python weekday: 월=0, 화=1, 수=2, 목=3, 금=4, 토=5, 일=6
    days_until_sunday = (6 - from_date.weekday()) % 7
    if days_until_sunday == 0:
        days_until_sunday = 7  # 오늘이 일요일이면 다음 주 일요일
    return from_date + timedelta(days=days_until_sunday)


def confirm_result(db: Session, match_id: int) -> Match:
    """
    결과 확정. 현재 경기일 이후 가장 빠른 일요일 경기 자동 생성.

    규칙:
    - 현재 경기가 일요일이면 다음 주 일요일 (+7일)
    - 현재 경기가 평일이면 그 주의 다음 일요일
    - 현재 경기일 기준이므로, 관리자가 과거 날짜로 수정 후 확정해도 항상 현재 경기일 이후가 됨
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")
    if match.status != "경기완료":
        raise ValueError("경기완료 상태에서만 확정할 수 있습니다.")

    match.status = "확정완료"

    # ★ 현재 경기일 이후의 가장 빠른 일요일 계산
    # Python: weekday() → 월=0, 화=1, ..., 일=6
    current = match.match_date
    days_until_sunday = (6 - current.weekday()) % 7
    if days_until_sunday == 0:
        # 현재 경기가 일요일 → 다음 주 일요일 (+7일)
        next_date = current + timedelta(days=7)
    else:
        # 평일 경기 → 그 주의 다음 일요일
        next_date = current + timedelta(days=days_until_sunday)

    existing_next = db.query(Match).filter(Match.match_date == next_date).first()
    if not existing_next:
        next_match = Match(match_date=next_date, status="투표중")
        db.add(next_match)

    db.commit()
    db.refresh(match)
    return match


def update_match_date(db: Session, match_id: int, new_date: date) -> Match:
    """
    경기 날짜 변경 (관리자 전용)
    - 과거 날짜 금지 (오늘 포함 가능)
    - 같은 날짜에 다른 경기 있으면 거부
    - 확정완료된 경기는 변경 불가
    - 투표/팀편성/결과 데이터는 모두 유지
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

    if match.status == "확정완료":
        raise ValueError("확정완료된 경기는 날짜를 변경할 수 없습니다. 확정취소 후 다시 시도하세요.")

    today = date.today()
    if new_date < today:
        raise ValueError(f"과거 날짜로 변경할 수 없습니다. (오늘: {today.isoformat()})")

    # 같은 날짜에 다른 경기 확인 (자기 자신 제외)
    conflict = db.query(Match).filter(
        Match.match_date == new_date,
        Match.id != match_id,
    ).first()
    if conflict:
        raise ValueError(f"{new_date.isoformat()} 날짜에 이미 다른 경기가 있습니다.")

    match.match_date = new_date
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


def delete_match(db: Session, match_id: int) -> None:
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

    db.query(MatchRecord).filter(MatchRecord.match_id == match_id).delete(synchronize_session=False)
    db.delete(match)
    db.commit()


def delete_member_cascade(db: Session, member_id: int) -> str:
    member = db.query(Member).filter(Member.id == member_id).first()
    if not member:
        raise ValueError("회원을 찾을 수 없습니다.")

    if member.phone == "01000000001":
        raise ValueError("시스템관리자 계정은 삭제할 수 없습니다.")

    name = member.name

    db.query(MatchRecord).filter(MatchRecord.member_id == member_id).delete(synchronize_session=False)
    db.delete(member)
    db.commit()
    return name
