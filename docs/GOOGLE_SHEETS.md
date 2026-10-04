# Google Sheets 연결

`/connections/`에서 자료원 **Google Sheets**를 선택하면 URL·연결 방식·탭 이름·헤더 행을 입력할 수 있습니다. 일반 사용자도 연결 등록과 OAuth 설정을 사용할 수 있습니다. 연결과 OAuth 자격 증명은 각 사용자 계정에 개별 저장되며 다른 사용자에게 표시되지 않습니다.

## 공개 링크

1. Google 시트의 공유 설정을 **링크가 있는 모든 사용자 → 뷰어**로 지정합니다.
2. 사용할 탭을 열고 주소를 복사합니다.
3. 연결 방식 **공개 링크 (로그인 없음)**을 선택하고 등록합니다.
4. **연결 테스트** 후 디자이너에서 해당 연결과 `공개 시트`를 선택합니다.

Google 로그인·API 키 없이 Google의 Visualization CSV 응답을 읽습니다. 새 데이터셋을 추가할 때 별도의 컬럼 타입 응답을 확인하고, Google이 숫자로 선언한 컬럼은 보고서의 `number` 타입과 `to_decimal` 변환 매핑으로 등록합니다. 기존 문자열 데이터셋과 매핑은 자동 변경하지 않습니다. 타입 정보를 가져올 수 없거나 CSV 컬럼과 일치하지 않으면 기존 문자열 방식으로 유지됩니다. 선택한 탭 하나만 연결되며 탭 이름을 지정하면 URL의 gid보다 우선합니다. 첫 행이 컬럼 제목이어야 합니다. 빈 탭 이름과 gid 없는 ID 입력은 gid=0을 사용합니다. 공개 연결의 컬럼명 `공개 시트`는 목록용 이름이며 원본 탭 이름을 자동 조회하지 않습니다.

특정 계정/조직에만 공유되었거나 다운로드가 금지된 시트는 공개 읽기가 실패할 수 있습니다. OAuth로 연결하세요. 공개 CSV는 Google의 형식/자료형 추론을 따르므로 혼합 자료형이나 정밀한 숫자·날짜가 중요한 시트는 OAuth 방식을 사용하고 미리보기 값을 확인하세요. 인증이 실패했다고 원본 시트의 공유 권한을 자동 변경하지 않습니다.

## 비공개 / 계정 공유 (OAuth)

### 1. Google Cloud 설정

- Google Cloud 프로젝트에서 **Google Sheets API**를 사용 설정합니다.
- Google Auth Platform에서 앱 동의 화면을 구성합니다. 테스트 중인 외부 앱이면 사용할 계정을 테스트 사용자로 등록합니다.
- OAuth Client ID를 **웹 애플리케이션**으로 생성합니다.
- `/connections/google/oauth/`에 표시된 **콜백 주소**를 승인된 리디렉션 URI에 그대로 등록합니다.
  - 로컬 예: `http://127.0.0.1:8000/connections/google/callback/`
  - 운영 예: `https://reports.example.com/connections/google/callback/`
  - localhost와 127.0.0.1, 포트, 끝의 슬래시까지 일치해야 합니다.
- 발급받은 Client ID와 Client Secret을 OAuth 설정 화면에 저장합니다.

설정은 현재 관리자 계정별로 저장됩니다. Secret을 비워 저장하면 기존 Secret을 유지합니다. Client ID를 변경하면 기존 연결은 새 앱으로 재인증해야 합니다. 운영에서는 HTTPS와 신뢰하는 프록시 설정을 사용하세요.

### 2. 인증과 연결

1. Google Sheets 연결을 **비공개 / 계정 공유 (OAuth)** 방식으로 등록합니다.
2. 등록 목록에서 **Google 인증 / 재인증**을 누릅니다.
3. 시트 조회 권한이 있는 Google 계정으로 로그인하고 읽기 전용 권한을 승인합니다.
4. 앱으로 돌아오면 **연결 테스트**를 누릅니다.
5. 디자이너에서 연결을 선택하면 조회 가능한 해당 문서의 모든 탭을 확인할 수 있습니다. OAuth 모드에서 등록 폼의 탭 이름은 필터로 쓰이지 않습니다.

앱은 `spreadsheets.readonly` 권한을 사용합니다. Google 계정 자체에 없는 파일 권한을 제공하지 않습니다. URL을 입력받는 방식이므로 범위는 해당 계정의 Sheets 읽기 권한이며 단일 파일로 제한되는 Google Picker 연동은 포함하지 않습니다.

액세스 토큰과 갱신 토큰은 암호화하여 서버에 보관하고 만료가 가까우면 서버에서 갱신합니다. 다른 관리자에게 토큰을 표시하거나 `.wrpx`에 포함하지 않습니다. Google에서 권한을 철회하거나 갱신 토큰이 만료되면 재인증해야 합니다. 테스트 상태 앱과 조직 정책에 따라 토큰 사용 기간 또는 승인이 제한될 수 있습니다.

**인증 연결 해제**는 해당 연결에 저장된 인증과 진행 중인 인증 요청을 삭제합니다. Google 계정 자체의 앱 권한도 없애려면 Google 계정의 서드 파티 연결 관리에서 해제하세요. 같은 앱을 사용하는 다른 연결에 영향을 주지 않도록 전체 앱 권한을 자동 철회하지 않습니다.

OAuth 브라우저 로그인과 공개 링크 읽기는 기본 의존성으로 실행됩니다. 기존 서비스 계정 JSON 방식은 계속 사용할 수 있으며 `uv sync --frozen --extra sheets`가 필요합니다.

## 업데이트

```powershell
uv run python manage.py migrate
uv run python manage.py runserver
```

기존 연결의 서비스 계정/수동 access_token 설정은 유지됩니다. 새 UI를 이용하려면 Google Sheets 연결을 새로 등록하세요. 기존 API의 JSON 등록도 지원합니다.

## 문제 해결

| 증상 | 확인 |
|---|---|
| redirect_uri_mismatch | OAuth 설정 화면의 콜백 주소와 Google Cloud 등록값 일치 |
| access_denied | 테스트 사용자 등록, 조직의 앱 승인 정책, 사용자 동의 |
| Google 인증 필요 | 목록의 Google 인증 / 재인증 실행 |
| 인증 완료 후 연결 실패 | Sheets API 활성화 및 로그인한 Google 계정의 원본 파일 접근 권한 |
| 공개 연결 실패 | 링크 전체 공개, 다운로드 허용, 탭 이름/gid, OAuth 방식 사용 |

## 검증 범위와 근거

자동 테스트는 Google 응답을 모의하여 인증 코드 교환, 토큰 갱신, state/CSRF/소유권 검사, 취소된 인증의 재사용 방지를 검증합니다. 실제 Google 프로젝트·계정으로의 동의 및 비공개 시트 조회는 배포 담당자의 자격 증명으로 확인해야 합니다.

- [Google Sheets 공개/비공개 조회](https://developers.google.com/chart/interactive/docs/spreadsheets)
- [Google OAuth 웹 서버 인증](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Sheets API 권한 범위](https://developers.google.com/workspace/sheets/api/scopes)
