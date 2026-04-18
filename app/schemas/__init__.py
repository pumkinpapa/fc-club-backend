from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel


# ─── 인증 ───
class KakaoLoginRequest(BaseModel):
    code: str


class PhoneLoginRequest(BaseModel):
    phone: str


class RegisterRequest(BaseModel):
    name: str
    birth: str
    phone: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    member: "MemberResponse"


# ─── 회원 ───
class MemberResponse(BaseModel):
    id: int
    name: str
    birth: str
    phone: str
    role: str
    status: str = "승인"
    join_date: Optional[datetime] = None
    note: str = ""

    class Config:
        from_attributes = True


class MemberUpdate(BaseModel):
    name: Optional[str] = None
    birth: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    note: Optional[str] = None


# ─── 경기 / 투표 ───
class MatchResponse(BaseModel):
    id: int
    match_date: date
    status: str
    result_summary: Optional[str] = None

    class Config:
        from_attributes = True


class VoteRequest(BaseModel):
    attendance: str


class MatchRecordResponse(BaseModel):
    id: int
    match_id: int
    member_id: int
    member_name: str = ""
    member_birth: str = ""
    attendance: str
    duty: str = ""
    team: str = ""
    match_result: str = ""

    class Config:
        from_attributes = True


class VoteStatusResponse(BaseModel):
    match: MatchResponse
    attendees: List[MatchRecordResponse]
    absentees: List[MatchRecordResponse]
    pending: List[MemberResponse]
    my_vote: Optional[str] = None


# ─── 팀 편성 ───
class TeamAssignmentResponse(BaseModel):
    match: MatchResponse
    teams: dict
    duties: dict


# ─── 경기 결과 ───
class ResultRequest(BaseModel):
    winning_team: str


# ─── 랭킹 ───
class RankingEntry(BaseModel):
    rank: int
    member_id: int
    name: str
    played: int
    wins: int
    draws: int
    losses: int
    points: int
    attendance_count: int


class RankingResponse(BaseModel):
    rankings: List[RankingEntry]
    total_matches: int
