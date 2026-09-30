# 개발 가이드 — WebReportingBuilder

작성일 2026-10-01. Python 3.12+, Django 5.2, uv 관리. 사용자 화면은 Django Template과 로컬 JavaScript/CSS로 실행합니다.

## 어디를 수정하나요?

| 파일 | 책임 |
|---|---|
| config/settings.py | 환경 변수·내부 DB·보안·정적 파일 |
| reportbuilder/models.py | 연결·프로젝트·보고서·버전·권한·실행 |
| reportbuilder/data.py | 커넥터·스키마·논리 조회 |
| reportbuilder/definition.py | 보고서/매개변수 계약 검사 |
| reportbuilder/rendering.py | 반복·페이지 계산·공통 HTML·PDF |
| reportbuilder/packaging.py | .wrpx 패키지 생성/검사 |
| reportbuilder/services.py | 권한·바인딩·행정책·snapshot 실행 |
| reportbuilder/views.py / urls.py | 화면·API·다운로드·임베드 |
| reportbuilder/static/reportbuilder/designer.js | 편집기 상태·이동·저장·매핑 |
| reportbuilder/static/reportbuilder/app.css | 공통 UI, indigo/slate 색상, 반응형 |
| reportbuilder/templates/reportbuilder/ | 로그인·대시보드·라이브러리·디자이너 |
| schemas/ | 개방 JSON Schema |
| tests/ | 데이터·페이지·패키지·권한·이식성 회귀 테스트 |

## 수정과 검증

```bash
uv sync --frozen
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
uv run pytest -q
uv build
```

모델 변경 시 migrations를 생성하고 커밋합니다. 신규 커넥터는 기존 테스트를 복제하는 것보다 실제 자료형·권한·타임아웃·한도·오류·매핑 시나리오를 검증합니다.

JS 디자이너는 undo/redo 명령으로 상태를 수정하고 server-side strict definition을 만족해야 합니다. DOM에 사용자 값은 textContent를 사용합니다. 직접 HTML 삽입·사용자 코드 실행을 추가하지 않습니다.

서버 스냅샷·정의·바인딩은 동일 실행에 고정합니다. 재다운로드에서는 현재 접근권한과 policy fingerprint를 확인합니다. 보안 기능을 프론트엔드 숨김 처리만으로 구현하지 않습니다.

## 운영 전 확인

현재는 alpha이며 외부 DB 실접속·브라우저/PDF 확인·대량 동시 부하·배포 의존성 라이선스 조합 검증을 수행해야 합니다. 상세 제한은 docs/SUPPORT_MATRIX.md에 있습니다. 키는 `.env`/secret manager로 관리하고 git에 넣지 않습니다.

## 후속 작업

JOIN/pushdown, 비동기 작업큐/취소, 정밀 텍스트 측정/큰 행 분할, DataTable/차트, 조직별 workspace/SSO, prefix/SDK 확대, 자동 저장·전체 키보드 접근성을 목표 명세에 맞춰 확장합니다.
