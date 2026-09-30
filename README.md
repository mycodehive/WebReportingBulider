# WebReportingBuilder

**Django로 만든 독립형 오픈소스 웹 레포트 빌더입니다.** Excel·CSV·DB·Google Sheets의 필드를 웹 캔버스에 배치하고, 저장한 보고서를 실행하거나 다른 설치 환경으로 옮길 수 있습니다.

Python 패키지는 **uv**로 관리합니다. UI는 로컬 CSS/JavaScript를 사용하므로 실행 전에 npm 빌드나 CDN 접속이 필요하지 않습니다.

## 빠른 시작

Python 3.12 이상과 [uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비하세요.

```bash
git clone https://github.com/mycodehive/WebReportingBulider.git
cd WebReportingBulider
uv sync --frozen
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py seed_demo
uv run python manage.py runserver
```

`http://127.0.0.1:8000/`에 접속해 생성한 관리자 계정으로 로그인합니다. **매출 현황 예제**를 열고 미리보기를 누르면 합성 데이터 65행이 여러 페이지로 출력됩니다.

PDF가 필요하면 추가로 설치합니다.

```bash
uv sync --frozen --extra pdf
uv run playwright install chromium
```

Linux에서는 Chromium 시스템 의존성과 한글 폰트도 설치해야 합니다. 상세 명령은 [설치 가이드](docs/INSTALL.md)를 확인하세요.

## 먼저 읽을 문서

| 문서 | 내용 |
|---|---|
| [사용 매뉴얼](docs/USER_MANUAL.md) | 연결 → 디자인 → 미리보기 → 게시 → 다른 DB로 재연결 |
| [설치 가이드](docs/INSTALL.md) | uv·PDF·선택 DB 드라이버·운영 설정·Docker |
| [쉬운 기술명세](docs/TECHNICAL_SPEC.md) | 현재 구현 구조·API·데이터 계약·지원 조건 |
| [타서비스 연동](docs/INTEGRATION.md) | 프로젝트 가져오기, Django 통합, API·iframe |
| [지원 현황](docs/SUPPORT_MATRIX.md) | 구현·테스트 완료와 미검증/후속 범위 구별 |
| [개발 가이드](CUSTOM.md) | 파일 위치·수정 방법·검증 명령 |
| [원래 목표 명세](docs/PLANNED_SPEC_v1.0.md) | 독립형 제품의 전체 목표. 현재 구현 완료 목록과 구별 |

로그인 후 서비스의 **사용 가이드** 메뉴에서도 매뉴얼을 읽을 수 있습니다.

## 현재 제공 기능

- 인증과 사용자/그룹별 보고서·연결 접근 통제.
- Excel·CSV·SQLite 및 선택 DB/API 커넥터의 스키마 탐색과 논리 컬럼 매핑.
- 텍스트·필드·이미지·선·사각형의 드래그 배치, 속성 편집, 페이지 추가/복제/삭제, undo/redo.
- 반복 Detail·그룹·합계·페이지 머리말/꼬리말, 자동/강제 페이지 넘김.
- 필터·정렬·실행 매개변수, 실제 서버 미리보기, HTML·XLSX·CSV 및 선택 PDF 출력.
- 수정본과 게시본 분리, 고정된 게시 버전·rollback.
- `.wrpx` 프로젝트 내보내기/가져오기, 타 환경 DB 재매핑, 이미지 이동.
- 만료·기능·보고서 범위가 있는 API 토큰, 단기 iframe 토큰.

## 릴리스 상태

**0.1.0 alpha**입니다. 전체 목표 명세의 정식 V1.0 완료를 선언하지 않습니다.

외부 Oracle/MSSQL/MariaDB/Google/Access 실자료 연결은 이 개발 환경에서 검증하지 못했습니다. 커넥터 코드는 제공하지만 설치 환경에서 실제 연결 시험이 필요합니다. 현재 조회는 단일 객체의 제한된 스냅샷이며 JOIN·쿼리 pushdown·비동기 작업큐·동시편집·차트·피벗·중첩 그룹은 후속 범위입니다. CSV/Excel의 숫자 컬럼은 명시 타입 변환이 필요할 수 있습니다.

PDF는 같은 출력 HTML을 Chromium으로 변환합니다. 개발 환경의 Chromium 다운로드 실패로 실제 브라우저 화면 및 PDF 페이지 일치 검증은 아직 완료하지 못했습니다. 긴 텍스트 높이는 보수적 추정이며 큰 분할 불가 밴드는 오류를 표시합니다.

## 검증 및 기여

```bash
uv sync --frozen
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
uv run pytest -q
uv build
# DOM 디자이너 시험에만 Node 24.15+ 필요
npm ci
npm test
```

PDF 테스트는 Chromium이 설치된 환경에서 실행됩니다. 설치되지 않은 경우 해당 테스트를 skip합니다. CI는 Chromium 설치 단계도 실행하여 다운로드 실패를 감춥니다.

자체 코드는 [Apache-2.0](LICENSE)로 배포합니다. 외부 DB 드라이버·브라우저·폰트의 라이선스는 별도이며 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 확인하세요. 사용자의 보고서/데이터 권리는 자동으로 프로젝트 코드 라이선스로 변경되지 않습니다.
