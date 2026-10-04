# 환경설정 API

전체 관리자는 **환경설정 → API**에서 내부API와 외부API를 선택합니다.
내부API에는 `실험실에 열심히 개발중이에요`를 표시합니다.

## 외부API · LLM 설정

1. **외부API**에서 연결명, 제공자, 모델명, HTTPS API 기본 주소, API 키를 입력합니다.
2. 제공자는 OpenAI, Anthropic, Google Gemini, OpenRouter, OpenAI 호환 API 중 선택합니다. 모델명과 주소는 사용하는 제공자의 문서에서 확인한 값을 입력합니다.
3. **LLM 설정 등록**을 누르면 등록 목록에 나타납니다. 여러 설정을 등록할 수 있습니다.
4. 목록의 **수정**에서 모델·주소·사용 여부를 변경합니다. API 키를 비우면 기존 키를 유지하고, 새 키를 입력하면 교체합니다.
5. **삭제**는 해당 설정과 암호화한 키를 함께 삭제합니다.

키는 기존 `REPORT_SECRET_KEY`로 암호화하고 화면에 다시 출력하지 않습니다. 운영 중 암호화 키를 변경하면 기존 키를 읽을 수 없으므로 백업·키 관리를 유지하세요.
현재 기능은 설정 저장이며 연결 확인, 모델 목록 조회, 보고서 AI 생성이나 실제 LLM 호출은 수행하지 않습니다. 저장된 사용 여부는 이후 호출 기능에서 사용할 설정값입니다.

`/menu-management/`에서 API 탭과 하위 메뉴의 이름·순서·사용 여부·소속을 관리할 수 있습니다.
기본 주소는 `/settings/api/internal/`, `/settings/api/external/`입니다.

## 적용

```powershell
git pull
uv run python manage.py migrate
uv run python manage.py runserver
```

마이그레이션 `0017_llmconfiguration`이 설정 저장 테이블과 API 메뉴를 생성합니다. 기존 환경설정 메뉴는 유지합니다.
