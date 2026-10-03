# 외부 의존성 고지

애플리케이션 자체 코드는 Apache-2.0입니다. 의존성·선택 DB 드라이버·Chromium·OS 패키지·폰트에는 각자의 라이선스가 적용됩니다. 이 저장소는 해당 공급자의 라이선스를 변경하지 않습니다.

## 재현 가능한 목록

Python 전체 패키지/버전은 `uv.lock`, 개발용 DOM 테스트 JavaScript 패키지/버전은 `package-lock.json`을 기준으로 확인합니다. UI에는 외부 CDN 코드·외부 웹폰트를 번들하지 않습니다.

| 구분 | 직접 의존성 |
|---|---|
| 웹/운영 | Django, WhiteNoise, Gunicorn, python-dotenv, Markdown |
| 데이터 | SQLAlchemy, openpyxl, httpx |
| 보안/이미지 | cryptography, Pillow |
| 선택 자료원 | psycopg, PyMySQL, python-oracledb, pyodbc, google-auth, requests |
| 선택 국가 조회 | geoip2, maxminddb 및 전이 의존성. GeoIP 국가 DB는 별도 준비 |
| PDF | Playwright 및 별도 설치 Chromium/OS 라이브러리 |
| 개발/시험 | pytest, pytest-django, Ruff, pypdf, jsdom 및 전이 의존성 |
| 게시판 UI | Summernote Lite 0.9.1, jQuery 3.7.1 (MIT); DOMPurify 3.4.16 (Apache-2.0). 로컬 정적 파일과 라이선스는 `reportbuilder/static/reportbuilder/vendor/`에 포함 |
| OS에서 별도 설치 | MDBTools, Microsoft ODBC Driver, Noto CJK 폰트 등 |

각 패키지에 함께 배포된 LICENSE/NOTICE 및 공식 공급자 문서를 확인하고, 바이너리/폰트/수정 코드를 재배포한다면 해당 고지도 포함하세요. 선택 독점 드라이버를 저장소에 동봉하지 않습니다. MDBTools 등 별도 도구를 이미지에 추가할 때도 그 배포 조건을 확인해야 합니다.

설치된 Python 패키지 메타정보 확인 예:

```bash
uv run python -c "from importlib.metadata import distributions; print('\n'.join(sorted(d.metadata['Name'] + ' ' + d.version for d in distributions())))"
```

이 파일은 의존성 출처 안내이며 완성된 SBOM/모든 배포 조합의 라이선스 검증 결과가 아닙니다. 정식 릴리스 전 실제 배포 이미지의 전이 의존성·브라우저·폰트까지 목록화하고 고지를 점검합니다.
