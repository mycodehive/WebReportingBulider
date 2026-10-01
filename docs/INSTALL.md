# 설치 가이드

## 1. 가장 쉬운 로컬 설치

Python 3.12+와 uv를 설치하고 저장소를 내려받습니다. Windows PowerShell에서도 아래 uv 명령은 동일합니다.

```bash
git clone https://github.com/mycodehive/WebReportingBulider.git
cd WebReportingBulider
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo
uv run python manage.py runserver
```

브라우저에서 `http://127.0.0.1:8000/`를 엽니다. 로그인 → 보고서 라이브러리 → 매출 현황 예제 → 미리보기 순서로 확인합니다.

`seed_demo`는 새 계정을 만들거나 비밀번호를 설정하지 않습니다. 기존 관리자에게 합성 CSV와 보고서를 추가하며 다시 실행해도 동일 예제를 중복 생성하지 않습니다. 특정 관리자를 선택하려면 `--username 내관리자`를 붙입니다. 기존 매출 예제가 꼬였거나 초기화가 필요하면 `uv run python manage.py seed_demo --reset`을 실행하세요. 이 명령은 해당 관리자 계정의 **매출 현황 예제 보고서**를 지운 뒤 다시 만들며, 다른 보고서가 공유하는 데이터 연결은 보존합니다.

## 2. uv 사용 방법

| 작업 | 명령 |
|---|---|
| 저장소의 고정 의존성 설치 | `uv sync --frozen` |
| Django 명령 실행 | `uv run python manage.py ...` |
| 패키지 CLI 실행 | `uv run webreport check` |
| 새 라이브러리 추가 | `uv add 라이브러리명` |
| 선택 의존성 추가 | `uv sync --frozen --extra pdf` |
| 패키지 빌드 | `uv build` |

`uv.lock`은 직접 편집하지 않고 커밋합니다. `uv sync`를 다른 extra 옵션으로 다시 실행하면 앞서 선택했던 extra가 빠질 수 있으므로 필요한 extra를 모두 함께 지정하세요.

## 3. 자료원별 추가 설치

| 자료원 | 명령/추가 준비 |
|---|---|
| Excel .xlsx/.xlsm, CSV, SQLite, REST | 기본 설치에 포함 |
| PostgreSQL | `uv sync --frozen --extra postgres` |
| MariaDB/MySQL | `uv sync --frozen --extra mariadb` |
| Oracle | `uv sync --frozen --extra oracle` — Thin 모드 기본 |
| MSSQL | `uv sync --frozen --extra mssql` + OS에 Microsoft ODBC Driver 설치 |
| Google Sheets | `uv sync --frozen --extra sheets` + 서비스 계정 또는 OAuth access token |
| Access | OS에 MDBTools 설치, 검증 가능한 .mdb/.accdb 파일 |

여러 자료원을 함께 쓰는 예:

```bash
uv sync --frozen --extra postgres --extra mariadb --extra oracle --extra sheets --extra pdf
```

Access의 MDBTools는 Ubuntu/Debian에서 `sudo apt install mdbtools`로 설치할 수 있습니다. Microsoft ODBC/Oracle Client 등은 공급자의 현재 약관·지원 OS에 맞춰 별도 설치하세요. 본 저장소는 독점 드라이버를 자동 동봉하거나 약관에 자동 동의하지 않습니다.

## 4. PDF 설치

```bash
uv sync --frozen --extra pdf
uv run playwright install chromium
```

Linux 시스템 의존성이 없으면 관리자 권한으로 설치합니다.

```bash
uv run playwright install --with-deps chromium
sudo apt install fonts-noto-cjk
```

Chromium 다운로드 서버에 접근할 수 있어야 합니다. 프록시·방화벽 때문에 설치가 실패하면 웹 HTML/XLSX/CSV는 사용할 수 있지만 PDF는 사용할 수 없습니다. 한글이 □로 표시되면 **PDF를 생성하는 서버**의 한글 폰트를 확인하세요.

## 5. 환경 변수

`.env.example`을 `.env`로 복사합니다. Linux/macOS는 `cp .env.example .env`, PowerShell은 `Copy-Item .env.example .env`입니다.

| 변수 | 의미 |
|---|---|
| `DJANGO_DEBUG` | 개발 `true`, 운영 `false` |
| `DJANGO_SECRET_KEY` | Django 인증/서명 키 |
| `REPORT_SECRET_KEY` | 연결 비밀정보 암호화용 Fernet 키 |
| `DJANGO_ALLOWED_HOSTS` | 쉼표로 구분한 허용 도메인 |
| `DATABASE_URL` | 내부 메타 DB의 PostgreSQL URL. 없으면 SQLite |
| `REPORT_MAX_ROWS` | 단일 데이터셋의 원본 조회 한도, 기본 10,000 |
| `REPORT_REST_ALLOWED_HOSTS` | REST 데이터 연결에 허용할 공인 API host |
| `EMBED_ALLOWED_ORIGINS` | iframe 허용 origin. 예: https://host.example |
| `DJANGO_TRUST_PROXY_HEADERS` | 신뢰하는 HTTPS 프록시 뒤에서만 true. 프록시가 외부 입력 X-Forwarded-Proto를 제거/덮어써야 함 |
| `WEBREPORT_BASE_DIR` | 패키지 설치 시 환경/DB/자산 저장 위치. 저장소 실행은 생략 |

키 생성:

```bash
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

첫 번째 결과는 `DJANGO_SECRET_KEY`, 두 번째는 `REPORT_SECRET_KEY`에 넣습니다. 키와 `.env`를 git에 커밋하지 마세요. 암호화 키를 분실하거나 바꾸면 기존 연결 비밀정보를 복호화할 수 없으므로 키를 별도로 백업하고 연결을 다시 등록해야 합니다.

## 6. 운영 실행

운영은 PostgreSQL을 권장합니다. HTTPS reverse proxy를 구성하고 아래를 실행합니다.

```bash
uv sync --frozen --no-dev --extra postgres --extra pdf
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 120
```

`DJANGO_DEBUG=false`이면 두 비밀 키가 없을 때 시작을 차단합니다. 정적 파일을 수집해야 운영 화면이 표시됩니다. 개발용 runserver를 운영 서버로 사용하지 않습니다. HTTPS를 프록시에서 종료한다면 위 조건을 만족한 후 `DJANGO_TRUST_PROXY_HEADERS=true`를 설정해 redirect loop를 방지합니다.

현재 작업은 HTTP 요청 내에서 실행됩니다. 대량 동시 PDF/무거운 외부 조회는 운영 시험이 필요하며 별도 작업큐는 후속 구현입니다. 사용자는 최대 원본 행 한도를 초과하면 전용 DB VIEW나 시트/파일 범위를 줄여야 합니다.

실행 스냅샷 보존 데이터 정리:

```bash
uv run python manage.py purge_executions --hours 24
```

운영 스케줄러에서 주기적으로 실행하고 `media/`, 내부 DB, 암호화 키를 백업합니다. `media/`를 공개 정적 디렉터리로 서비스하지 않습니다.

## 7. Docker

```bash
docker compose build
docker compose run --rm web uv run python manage.py migrate
docker compose run --rm web uv run python manage.py createsuperuser
docker compose run --rm web uv run python manage.py seed_demo
docker compose up -d
```

기본 Compose는 `127.0.0.1:8000`의 로컬 데모용입니다. Docker 이미지에 PDF/외부 DB 드라이버는 기본 설치하지 않습니다. PDF 이미지는 `Dockerfile.pdf`를 선택해 별도 build합니다: `docker build -f Dockerfile.pdf -t webreport-pdf .`. 이 환경에서는 Docker 이미지의 실제 build/run을 검증하지 못했습니다. 운영 전 `.env`·HTTPS·PostgreSQL 연결·드라이버를 설정해야 합니다.

## 8. 자주 만나는 설치 문제

| 문제 | 확인 |
|---|---|
| migrate할 항목이 없다는 메시지 | 정상일 수 있습니다. `showmigrations reportbuilder`로 체크 표시 확인 |
| 빈 보고서 목록 | `seed_demo` 실행 또는 새 보고서 생성 |
| DRIVER_MISSING | 해당 extra와 OS 드라이버 설치 |
| PDF renderer unavailable | Chromium 설치·시스템 의존성 확인 |
| DB 연결 성공, 조회 실패 | 테이블/컬럼 권한과 실제 매핑 확인 |
| 운영 CSS가 안 보임 | `collectstatic`, STATIC_ROOT, reverse proxy 설정 확인 |
| 자료형이 다르다는 오류 | 재연결에서 명시적인 타입 변환 선택 |
