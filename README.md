# Family CFO

가족 5명이 공동자금, 투자, 목표, 일정, 할 일과 투표를 함께 관리하는 모바일 우선 Streamlit 앱입니다.

## 실행

Python 3.10 이상을 권장합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

최초 실행 시 `data/family_cfo.db`와 샘플 데이터가 자동 생성됩니다. 테스트는 `pytest -q`로 실행합니다.

앱 비밀번호는 공개 코드에 넣지 않습니다. 로컬에서는 환경변수 `APP_PASSWORD`를 사용하고, Streamlit Cloud에서는 App settings의 Secrets에 아래처럼 저장합니다.

```toml
APP_PASSWORD = "가족 비밀번호"
```

## Yahoo Finance 티커

- 미국 주식: `AAPL`, `MSFT`
- 코스피: 삼성전자 `005930.KS`
- 코스닥: 종목코드 뒤에 `.KQ`
- 한국 ETF: TIGER 미국S&P500 `360750.KS`

미국 자산은 `KRW=X` 환율로 원화 환산합니다. 조회 실패 시 마지막 저장 가격, 그다음 수동 입력 가격을 사용합니다. 예금·채권·기타는 수동 평가금액을 지원합니다.

## GitHub 업로드

```bash
git init
git add .
git commit -m "Build Family CFO MVP"
git branch -M main
git remote add origin https://github.com/USERNAME/family-cfo.git
git push -u origin main
```

## Streamlit Community Cloud

1. GitHub 저장소를 [Streamlit Community Cloud](https://share.streamlit.io/)에 연결합니다.
2. 브랜치는 `main`, Main file path는 `app.py`로 설정합니다.
3. 배포하면 `requirements.txt`가 자동 설치됩니다.

SQLite는 Streamlit Cloud 재시작·재배포 시 초기화될 수 있습니다. 장기 운영에는 Supabase를 사용하세요.

## 데이터베이스

`users`, `cash_transactions`, `investment_assets`, `investment_transactions`, `price_cache`, `goals`, `events`, `tasks`, `polls`, `poll_options`, `poll_votes` 테이블을 사용합니다. 투자 매도는 이동평균 원가로 남은 투자원금을 계산합니다.

## Next.js·Supabase 확장

1. `database.py` 저장 계층을 Supabase Repository로 교체합니다.
2. 가족 그룹 ID, Supabase Auth, Row Level Security를 추가합니다.
3. Next.js App Router·TypeScript·Tailwind로 UI를 옮깁니다.
4. 가격 조회를 서버 함수나 예약 작업으로 분리합니다.

향후 은행·증권 연동, 반복 일정, 알림, 배당·세금, 문서함과 데이터 내보내기를 추가할 수 있습니다.
