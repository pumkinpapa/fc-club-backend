# FC 동호회 - 축구 동호회 운영 관리 백엔드

Python FastAPI + SQLite + 솔라피(Solapi) 알림톡 연동 백엔드 서버

## 📋 주요 기능

1. **회원관리** - 카카오 로그인 인증, 회원 CRUD, JWT 자동 로그인
2. **경기 참석 투표** - 매주 수요일 알림톡 자동 발송, 참석 응답 수집
3. **팀/역할 편성** - 골대담당 2명, 음료담당 1명 랜덤 배정, 자동 팀 구성
4. **경기 결과 기록** - 관리자 경기 결과 입력, DB 업데이트
5. **누적 랭킹 조회** - 승점 기반 누적 순위표 제공

## 🛠 기술 스택

- **Framework**: FastAPI
- **Database**: SQLite (SQLAlchemy ORM)
- **인증**: JWT (PyJWT)
- **알림톡**: 솔라피(Solapi) REST API
- **스케줄러**: APScheduler (매주 수요일 자동 알림)

## 🚀 설치 및 실행

### 1. 필수 준비사항

- Python 3.10+
- 솔라피 계정 및 API Key 발급 (https://solapi.com)
- 카카오 개발자 계정 (https://developers.kakao.com)

### 2. 의존성 설치

```bash
cd fc-club-backend
pip install -r requirements.txt
```

### 3. 환경변수 설정

`.env.example`을 `.env`로 복사하고 값을 채워주세요:

```bash
cp .env.example .env
```

### 4. 서버 실행

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. API 문서 확인

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 📱 솔라피 사전 설정

1. https://solapi.com 회원가입
2. [설정] > [API Key 관리]에서 API Key / API Secret 발급
3. 카카오 비즈니스 채널 개설 후 솔라피에 연동
4. 알림톡 템플릿 등록 및 검수 (아래 템플릿 참고)

### 알림톡 템플릿 예시

**템플릿 코드**: `MATCH_VOTE`
```
[FC 동호회] 이번 주 경기 참석 투표

안녕하세요, #{이름}님!
#{경기일} 일요일 오전 경기에 참석하시나요?

아래 버튼을 눌러 참석 여부를 알려주세요.
```

**템플릿 코드**: `MATCH_RESULT`
```
[FC 동호회] 팀 편성 안내

#{경기일} 경기 편성 결과입니다.

#{이름}님은 #{팀}에 배정되었습니다.
#{담당}

좋은 경기 되세요! ⚽
```

## 📂 프로젝트 구조

```
fc-club-backend/
├── app/
│   ├── main.py              # FastAPI 앱 진입점
│   ├── core/
│   │   ├── config.py         # 환경변수 설정
│   │   ├── database.py       # DB 연결
│   │   └── security.py       # JWT 인증
│   ├── models/
│   │   └── models.py         # SQLAlchemy 모델
│   ├── schemas/
│   │   └── schemas.py        # Pydantic 스키마
│   ├── services/
│   │   ├── solapi_service.py  # 솔라피 알림톡 발송
│   │   ├── kakao_service.py   # 카카오 로그인
│   │   ├── match_service.py   # 경기/투표 로직
│   │   └── scheduler.py       # 수요일 자동 알림
│   └── api/
│       ├── auth.py            # 인증 API
│       ├── members.py         # 회원 API
│       ├── matches.py         # 경기/투표 API
│       └── rankings.py        # 랭킹 API
├── requirements.txt
├── .env.example
└── README.md
```
