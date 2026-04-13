"""
매주 수요일 자동 알림 스케줄러

APScheduler를 사용하여 매주 수요일 지정 시간에
모든 회원에게 경기 참석여부 알림톡을 발송합니다.
"""

import asyncio
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Member, Match, MatchRecord
from app.services.solapi_service import send_alimtalk_bulk
from app.services.match_service import get_next_match_date, get_or_create_match

settings = get_settings()
scheduler = AsyncIOScheduler()


async def send_vote_notifications():
    """
    모든 회원에게 경기 참석여부 알림톡 발송

    매주 수요일 실행:
    1. 다음 일요일 경기를 생성 (없으면)
    2. 모든 회원에게 알림톡 발송
    """
    print("[스케줄러] 경기 참석여부 알림톡 발송 시작...")

    db: Session = SessionLocal()
    try:
        # 다음 일요일 날짜
        match_date = get_next_match_date(settings.match_day_of_week)
        match = get_or_create_match(db, match_date)

        # 모든 회원 조회
        members = db.query(Member).all()
        if not members:
            print("[스케줄러] 등록된 회원이 없습니다.")
            return

        # 알림톡 수신자 목록 구성
        recipients = []
        for member in members:
            if member.phone:
                recipients.append({
                    "to": member.phone,
                    "variables": {
                        "#{이름}": member.name,
                        "#{경기일}": match_date.strftime("%m월 %d일"),
                    },
                })

        if recipients:
            # 솔라피 대량 알림톡 발송
            result = await send_alimtalk_bulk(
                recipients=recipients,
                template_id=settings.solapi_template_vote,
            )
            print(f"[스케줄러] 알림톡 발송 완료: {len(recipients)}명, 결과: {result}")
        else:
            print("[스케줄러] 발송 대상 회원이 없습니다.")

    except Exception as e:
        print(f"[스케줄러] 알림톡 발송 중 오류 발생: {e}")
    finally:
        db.close()


def start_scheduler():
    """스케줄러 시작"""
    # 매주 수요일 지정 시간에 실행
    scheduler.add_job(
        send_vote_notifications,
        CronTrigger(
            day_of_week=settings.vote_notify_day,  # 수요일 = 2
            hour=settings.vote_notify_hour,
            minute=settings.vote_notify_minute,
        ),
        id="weekly_vote_notification",
        name="매주 수요일 경기 참석여부 알림",
        replace_existing=True,
    )

    scheduler.start()
    print(
        f"[스케줄러] 시작됨 - 매주 "
        f"{'월화수목금토일'[settings.vote_notify_day]}요일 "
        f"{settings.vote_notify_hour:02d}:{settings.vote_notify_minute:02d}에 "
        f"알림톡 발송"
    )


def stop_scheduler():
    """스케줄러 중지"""
    if scheduler.running:
        scheduler.shutdown()
        print("[스케줄러] 중지됨")
