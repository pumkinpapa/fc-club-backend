"""
경기/투표/팀편성 비즈니스 로직
"""

import random
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Match, MatchRecord, Member


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
    - 7 vs 7 경기 기준
    """
    records = (
        db.query(MatchRecord)
        .filter(MatchRecord.match_id == match_id, MatchRecord.attendance == "참석")
        .all()
    )

    if len(records) < 3:
        raise ValueError("최소 3명 이상이 참석해야 팀 편성이 가능합니다.")

    # 랜덤 셔플
    shuffled = list(records)
    random.shuffle(shuffled)

    # 역할 배정
    goal_keepers = shuffled[:2]  # 골대담당 2명
    drink_person = shuffled[2]  # 음료담당 1명

    for r in records:
        r.duty = ""
    for r in goal_keepers:
        r.duty = "골대"
    drink_person.duty = "음료" if drink_person.duty != "골대" else "음료, 골대"

    # 팀 편성 (모든 참석자 대상)
    num_teams = 3 if len(records) >= 21 else 2
    for i, record in enumerate(shuffled):
        record.team = f"{(i % num_teams) + 1}팀"

    # 경기 상태 업데이트
    match = db.query(Match).filter(Match.id == match_id).first()
    match.status = "편성완료"

    db.commit()

    # 결과 정리
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

    - winning_team이 "무승부"이면 모두 무승부 처리
    - 그 외에는 해당 팀 승리, 나머지 패배
    """
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        raise ValueError("경기를 찾을 수 없습니다.")

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
    """
    누적 승점 랭킹 계산

    승: 3점, 무: 1점, 패: 0점
    """
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

    # 승점 순 → 승리 수 순 정렬
    ranked = sorted(
        stats.values(),
        key=lambda x: (x["points"], x["wins"]),
        reverse=True,
    )

    for i, entry in enumerate(ranked):
        entry["rank"] = i + 1

    return ranked
