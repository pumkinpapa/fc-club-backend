"""
솔라피(Solapi) 알림톡 발송 서비스

솔라피 API 문서: https://docs.solapi.com
인증 방식: HMAC-SHA256
"""

import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import get_settings

settings = get_settings()

SOLAPI_BASE_URL = "https://api.solapi.com"


def _generate_auth_header() -> str:
    """솔라피 HMAC-SHA256 인증 헤더 생성"""
    date_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    salt = secrets.token_hex(16)

    # Signature = HMAC-SHA256(apiSecret, dateTime + salt)
    data = date_time + salt
    signature = hmac.new(
        settings.solapi_api_secret.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()

    return (
        f"HMAC-SHA256 apiKey={settings.solapi_api_key}, "
        f"date={date_time}, salt={salt}, signature={signature}"
    )


async def send_alimtalk(
    to: str,
    template_id: str,
    variables: dict,
    subject: Optional[str] = None,
) -> dict:
    """
    카카오 알림톡 단일 발송

    Args:
        to: 수신자 전화번호 (예: "01012345678")
        template_id: 솔라피에 등록된 알림톡 템플릿 코드
        variables: 템플릿 치환 변수 (예: {"#{이름}": "홍길동"})
        subject: 제목 (선택)

    Returns:
        솔라피 API 응답 dict
    """
    # 전화번호 하이픈 제거
    to_clean = to.replace("-", "")

    headers = {
        "Authorization": _generate_auth_header(),
        "Content-Type": "application/json",
    }

    # 템플릿 변수를 적용한 텍스트 생성
    # 솔라피에서 템플릿 검수 시 등록한 내용과 동일해야 함
    text = ""
    for key, value in variables.items():
        text = text  # 텍스트는 솔라피에서 템플릿 기반으로 자동 생성

    payload = {
        "message": {
            "to": to_clean,
            "from": settings.solapi_sender_phone.replace("-", ""),
            "kakaoOptions": {
                "pfId": settings.solapi_pfid,
                "templateId": template_id,
                "variables": variables,
            },
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLAPI_BASE_URL}/messages/v4/send",
            json=payload,
            headers=headers,
            timeout=30.0,
        )

    result = response.json()

    if response.status_code != 200:
        print(f"[솔라피] 알림톡 발송 실패: {result}")
    else:
        print(f"[솔라피] 알림톡 발송 성공: to={to_clean}")

    return result


async def send_alimtalk_bulk(
    recipients: list[dict],
    template_id: str,
) -> dict:
    """
    카카오 알림톡 대량 발송 (그룹 메시지)

    Args:
        recipients: [{"to": "01012345678", "variables": {"#{이름}": "홍길동"}}]
        template_id: 솔라피에 등록된 알림톡 템플릿 코드

    Returns:
        솔라피 API 응답 dict
    """
    headers = {
        "Authorization": _generate_auth_header(),
        "Content-Type": "application/json",
    }

    # Step 1: 그룹 생성
    async with httpx.AsyncClient() as client:
        # 그룹 생성
        group_res = await client.post(
            f"{SOLAPI_BASE_URL}/messages/v4/groups",
            json={},
            headers=headers,
            timeout=30.0,
        )
        group_data = group_res.json()
        group_id = group_data.get("groupId")

        if not group_id:
            print(f"[솔라피] 그룹 생성 실패: {group_data}")
            return group_data

        # Step 2: 그룹에 메시지 추가
        # 인증 헤더 재생성 (Signature 재사용 불가)
        messages = []
        for recipient in recipients:
            to_clean = recipient["to"].replace("-", "")
            messages.append({
                "to": to_clean,
                "from": settings.solapi_sender_phone.replace("-", ""),
                "kakaoOptions": {
                    "pfId": settings.solapi_pfid,
                    "templateId": template_id,
                    "variables": recipient.get("variables", {}),
                },
            })

        add_headers = {
            "Authorization": _generate_auth_header(),
            "Content-Type": "application/json",
        }
        await client.put(
            f"{SOLAPI_BASE_URL}/messages/v4/groups/{group_id}/messages",
            json={"messages": messages},
            headers=add_headers,
            timeout=30.0,
        )

        # Step 3: 발송 요청
        send_headers = {
            "Authorization": _generate_auth_header(),
            "Content-Type": "application/json",
        }
        send_res = await client.post(
            f"{SOLAPI_BASE_URL}/messages/v4/groups/{group_id}/send",
            json={},
            headers=send_headers,
            timeout=30.0,
        )
        result = send_res.json()

    print(f"[솔라피] 대량 알림톡 발송 완료: {len(recipients)}건")
    return result


async def send_sms(to: str, text: str) -> dict:
    """
    일반 SMS 발송 (알림톡 실패 시 대체 발송 또는 인증번호 발송용)

    Args:
        to: 수신자 전화번호
        text: 문자 내용

    Returns:
        솔라피 API 응답 dict
    """
    to_clean = to.replace("-", "")

    headers = {
        "Authorization": _generate_auth_header(),
        "Content-Type": "application/json",
    }

    payload = {
        "message": {
            "to": to_clean,
            "from": settings.solapi_sender_phone.replace("-", ""),
            "text": text,
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SOLAPI_BASE_URL}/messages/v4/send",
            json=payload,
            headers=headers,
            timeout=30.0,
        )

    return response.json()
