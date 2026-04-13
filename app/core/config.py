from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ─── 서버 ───
    app_name: str = "FC동호회"
    secret_key: str = "change-me"
    database_url: str = "sqlite:///./fc_club.db"
    access_token_expire_minutes: int = 60 * 24 * 30  # 30일 (자동 로그인)

    # ─── 솔라피 ───
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    solapi_sender_phone: str = ""
    solapi_pfid: str = ""
    solapi_template_vote: str = "MATCH_VOTE"
    solapi_template_result: str = "MATCH_RESULT"

    # ─── 카카오 ───
    kakao_client_id: str = ""
    kakao_client_secret: str = ""
    kakao_redirect_uri: str = "http://localhost:8000/api/auth/kakao/callback"

    # ─── 경기 설정 ───
    match_day_of_week: int = 6  # 일요일
    vote_notify_day: int = 2  # 수요일
    vote_notify_hour: int = 10
    vote_notify_minute: int = 0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
