"""
누적 랭킹 API
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Member, Match
from app.schemas import RankingResponse, RankingEntry
from app.services.match_service import get_rankings

router = APIRouter(prefix="/api/rankings", tags=["랭킹"])


@router.get("/", response_model=RankingResponse)
async def get_ranking(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    누적 승점 랭킹 조회

    승: 3점, 무: 1점, 패: 0점
    승점 → 승수 순 정렬
    """
    rankings = get_rankings(db)
    total_matches = (
        db.query(Match).filter(Match.status == "경기완료").count()
    )

    return RankingResponse(
        rankings=[RankingEntry(**r) for r in rankings],
        total_matches=total_matches,
    )
