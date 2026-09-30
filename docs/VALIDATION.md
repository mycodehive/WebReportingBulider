# 검증 기록

기준: 0.1.0 alpha, 2026-09-30.

[GitHub Actions 결과](https://github.com/mycodehive/WebReportingBulider/actions/runs/36783949922)

- uv 고정 설치, Django check, migration drift check, Ruff 통과.
- Python **101 passed**. Chromium을 실제 설치해 PDF 페이지 수·mm 크기·텍스트 검사도 통과.
- DOM 통합: UI 정의 5개 검증, 실제 Excel 재매핑·필터·집계·2페이지 렌더링 통과.
- wheel/sdist 빌드 통과.
- 로컬 운영 설정의 collectstatic/check 통과.

로컬 개발 환경은 Chromium 다운로드 실패로 Python 100 passed/1 skipped였습니다. CI에서는 같은 PDF 테스트가 실제 실행되었습니다.

시각적인 브라우저 화면 검사, 다양한 한글 폰트·긴 텍스트의 출력 품질, 외부 Oracle/MSSQL/MariaDB/PostgreSQL/Sheets/Access 실연결, Docker build/run은 아직 검증하지 못했습니다. 테스트 통과가 정식 V1.0 목표의 모든 기능 완료를 의미하지 않습니다.
