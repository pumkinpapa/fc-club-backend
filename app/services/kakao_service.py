"""
카카오 로그인 OAuth2 연동 서비스

카카오 디벨로퍼스: https://developers.kakao.com
"""

import httpx
from app.core.config import get_settings

settings = get_settings()

KAKAO_AUTH_URL = "https://kauth.kakao.com"
KAKAO_API_URL = "https://kapi.kakao.com"


def get_kakao_login_url() -> str:
    """카카오 로그인 페이지 URL 생성"""
    return (
        f"{KAKAO_AUTH_URL}/oauth/authorize"
        f"?client_id={settings.kakao_client_id}"
        f"&redirect_uri={settings.kakao_redirect_uri}"
        f"&response_type=code"
        f"&scope=phone_number,profile_nickname,birthday"
    )


async def get_kakao_token(code: str) -> dict:
    """인증 코드로 액세스 토큰 발급"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KAKAO_AUTH_URL}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": settings.kakao_client_id,
                "client_secret": settings.kakao_client_secret,
                "redirect_uri": settings.kakao_redirect_uri,
                "code": code,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
    return response.json()


async def get_kakao_user_info(access_token: str) -> dict:
    """
    카카오 사용자 정보 조회

    Returns:
        {
            "id": 카카오 고유 ID,
            "name": 이름 또는 닉네임,
            "phone": 전화번호 (동의 시),
            "birthday": 생일 (동의 시),
        }
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{KAKAO_API_URL}/v2/user/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
        )

    data = response.json()
    kakao_account = data.get("kakao_account", {})
    profile = kakao_account.get("profile", {})

    # 전화번호 형식 변환: +82 10-1234-5678 → 010-1234-5678
    phone_raw = kakao_account.get("phone_number", "")
    phone = ""
    if phone_raw:
        phone = phone_raw.replace("+82 ", "0").replace(" ", "")

    # 생일: MMDD 형식
    birthday = kakao_account.get("birthday", "")

    return {
        "id": str(data.get("id", "")),
        "name": profile.get("nickname", ""),
        "phone": phone,
        "birthday": birthday,
    }
