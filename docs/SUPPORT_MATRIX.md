# 지원 및 검증 현황

기준 버전: 0.1.0 alpha. **코드 구현과 실제 외부 시스템 연결 검증은 다릅니다.**

| 기능/자료원 | 구현 | 현재 검증 |
|---|---|---|
| Excel .xlsx/.xlsm | cached/read-only 파일·시트 분석 | 합성 로컬 workbook 테스트 |
| CSV/TSV | 헤더/컬럼/논리 매핑/필터 | 로컬 자료 및 웹 통합 테스트 |
| SQLite | table/view 분석, readonly | 임시 실제 SQLite 조회/보안 테스트 |
| PostgreSQL/MariaDB/MySQL | SQLAlchemy/선택 드라이버 | 실제 원격 DB 미검증 |
| Oracle | python-oracledb Thin | 실제 원격 DB 미검증 |
| MSSQL | pyodbc/ODBC 설정 | 실제 원격 DB 미검증 |
| Google Sheets | API/서비스계정/access token | 계약·응답 mock, 실제 계정 미검증 |
| Access | MDBTools 로컬 파일 추출 | 명령/제약 mock, 실제 MDBTools 파일 미검증 |
| REST/JSON | 고정 HTTPS, records_path | HTTP/IP/allowlist/redirect 보안 테스트, 실제 공급자 미검증 |
| 자유배치/반복 페이지 | DOM 디자이너/Python 페이지 엔진 | DOM·정의·서버 HTML 통합 |
| HTML/XLSX/CSV | 동일 실행 snapshot 내보내기 | 실제 파일/셀/권한 시험 |
| PDF | Playwright 공통 HTML 출력 | GitHub CI에서 실제 PDF 페이지 수·mm 크기·텍스트 검증 통과; 시각 검증은 미완료 |
| `.wrpx` 이식 | 정의/자산/계약 import/export | 악성 ZIP/변조/매핑 누락/재연결 시험 |
| 게시/그룹/행/마스킹 | 서버 통제 | Django 통합 보안 테스트 |
| iframe/Bearer | origin/nonce/scope/expiry | Django 통합 시험, 실제 외부 브라우저 미검증 |

## 제한 및 후속 범위

- 데이터셋당 단일 객체. JOIN/다른 원본 간 JOIN 미지원.
- 원본 한도 내 전체 스냅샷 처리. SQL 필터 pushdown 미지원.
- 고정 endpoint REST만 지원. 임의 페이지네이션·GraphQL·사이트 로그인 스크래핑 미지원.
- 단일 그룹, fixed/flow, 기본 raster 이미지. 독립 DataTable/차트/피벗/서브리포트/중첩 그룹/HTML/SVG 미지원.
- 페이지보다 큰 단일 grow 밴드 오류. 긴 텍스트 정밀 줄 측정·행 내부 분할은 후속 범위.
- 동기 작업. 작업 큐·사용자별 취소·진행률·자동 스케줄링은 후속 범위.
- 사용자/그룹 격리. 독립 조직(workspace) SaaS·OIDC SSO·실시간 공동편집 미지원.
- 디자이너는 명시 저장/undo/redo/저장 충돌 처리를 제공. 자동 저장·전체 키보드 접근성 고도화는 후속 범위.
- Oracle Thick, 암호화 Access·링크/복합 필드, Excel .xls/.xlsb 정식 검증은 별도 필요.
- 자체 코어 Apache-2.0. 선택 드라이버/폰트/브라우저 라이선스는 실제 배포 조합에서 검토.

정식 V1.0의 전체 목표는 PLANNED_SPEC_v1.0.md를 기준으로 관리하며, 현재 테스트가 목표의 모든 수용 기준을 만족했다고 표시하지 않습니다.
