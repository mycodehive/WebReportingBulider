# 다른 서비스에서 사용하기

## 1. 프로젝트를 다른 설치로 옮기는 방법

원래 설치에서 `.wrpx`를 내보내고, 대상 설치의 라이브러리에서 가져옵니다. 데이터 연결과 컬럼 매핑을 새로 지정하면 디자인을 유지할 수 있습니다. 비밀번호·원본 데이터 파일·원본 권한은 이동하지 않습니다.

대상 DB에 의미가 같은 컬럼이 필요합니다. 필요한 경우 보고서용 VIEW를 만들어 논리 데이터 계약을 맞춥니다. 현재 single object이므로 여러 업무테이블을 결합하려면 대상 DB VIEW가 적합합니다.

## 2. 기존 Django에 설치

패키지를 로컬 wheel 또는 git으로 설치할 수 있습니다.

```bash
uv add "web-reporting-builder @ git+https://github.com/mycodehive/WebReportingBulider.git@YOUR_COMMIT_SHA"
```

호스트 settings에 `reportbuilder`를 INSTALLED_APPS로 추가하고 templates APP_DIRS, staticfiles, Pillow/crypto 환경을 준비합니다. `REPORT_SECRET_KEY`, `REPORT_MAX_ROWS`, `REPORT_REST_ALLOWED_HOSTS`, `EMBED_ALLOWED_ORIGINS`를 설정합니다.

호스트 `AUTH_USER_MODEL`과 Django 그룹을 그대로 사용합니다. 보고서 migrations를 호스트 DB에 설치하고 URL을 연결합니다.

```python
from django.urls import include, path
urlpatterns += [path("", include("reportbuilder.urls"))]
```

현재 UI는 `/api/`, `/reports/`, `/connections/` 루트 경로를 사용하므로 다른 prefix에 그대로 mount하는 것은 지원하지 않습니다. 호스트 루트 경로가 충돌하면 별도 subdomain Django 런타임을 사용하세요. 경로 prefix 설정은 후속 범위입니다.

패키지 standalone config 대신 호스트 settings를 사용하는 경우 파일 정책·암호화·인증/CSRF middleware 설정을 맞춰야 합니다. Bearer 연동을 쓰려면 `ApiAuthenticationMiddleware`와 `ApiAwareCsrfMiddleware`를 standalone settings와 같은 순서로 설정합니다.

## 3. 분리 서비스의 게시 보고서 호출

원본 데이터 연결을 구성하고 보고서를 게시합니다. 서버에 범위 제한 토큰을 생성합니다.

```bash
uv run python manage.py create_api_token --username 호스트사용자 --report 보고서UUID --hours 24
```

토큰은 한 번만 출력되며 내부 DB에는 SHA-256 digest만 저장합니다. 호스트 서버의 비밀 저장소에 보관합니다. 브라우저에 넣지 않습니다. 기본 scope는 read/run/embed입니다. 특정 기능만 부여하려면 `--scope run`처럼 지정합니다. 그룹/보고서 권한이 회수되면 유효 토큰도 실행할 수 없습니다.

호스트 서버 Python 예제:

```python
import os
import httpx

base = os.environ["REPORT_BASE_URL"]
token = os.environ["REPORT_API_TOKEN"]
report_id = os.environ["REPORT_ID"]
response = httpx.post(
    f"{base}/api/reports/{report_id}/execute/",
    headers={"Authorization": f"Bearer {token}"},
    json={"parameters": {}}, timeout=120,
)
response.raise_for_status()
result = response.json()
# result['html'] is the generated report, result['execution_id'] is the snapshot ID.
```

현재 실행은 동기입니다. 응답에 안전한 페이지 HTML을 포함합니다. 브라우저에 표시할 때 iframe sandbox를 사용하고 호스트 서비스의 권한도 확인합니다. 데이터 원본이 자동 공개되는 정적 URL로 게시하지 않습니다.

## 4. iframe 임베드

런타임 서버 `.env`에 호스트 origin을 허용합니다.

```dotenv
EMBED_ALLOWED_ORIGINS=https://your-service.example
```

호스트 서버가 `/api/embed-sessions/`에 Bearer 토큰과 아래 body로 요청합니다.

```json
{"report_id": "보고서UUID", "origin": "https://your-service.example", "parameters": {}}
```

반환된 단기 token을 호스트 페이지의 form POST로 iframe에 전달합니다. token은 60초이고 한 번만 사용 가능합니다. URL query에 장기 credential을 넣지 않습니다.

```html
<iframe name="report-frame" title="보고서" style="width:100%;height:900px;border:0"></iframe>
<form id="report-form" method="post" action="https://reports.example/embed/" target="report-frame">
  <input type="hidden" name="token" value="SERVER_ESCAPED_SHORT_LIVED_TOKEN">
  <button type="submit">보고서 보기</button>
</form>
```

실제 템플릿 엔진의 HTML escape로 토큰을 넣고 호스트 HTTPS Origin이 발급 범위와 일치하도록 합니다. `examples/embed-client.js`는 호스트 서버가 제공한 단기 토큰을 iframe으로 보내는 작은 helper입니다.

초기 임베드는 단일 출력 HTML입니다. 페이지 이동 postMessage protocol, runtime parameter 변경, 외부 iframe 다운로드 UI의 완전한 SDK는 후속 범위입니다.

## 5. 커넥터 확장

서버가 설치한 Python 플러그인은 introspect와 read를 구현하고 `register_connector`로 등록할 수 있습니다. 업로드된 보고서 파일에서 import 경로나 코드를 실행하지 않습니다.

`examples/custom_connector.py`의 예제는 정규화된 객체/컬럼·bounded row 읽기 계약을 보여줍니다. 웹 연결 등록 폼의 새로운 kind 지원은 관리자가 함께 등록해야 합니다. 모든 자료원을 즉시 자동 인식한다는 의미는 아닙니다.
