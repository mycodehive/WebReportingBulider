# 공개 소개페이지

`/intro`와 `/intro/`는 업로드된 intro.zip의 index.html을 공개 소개페이지로 표시합니다. 로그인하지 않은 방문자와 메일 인증 전 사용자도 열람할 수 있습니다. 보고서·연결의 기존 권한과 인증 제한은 유지됩니다.

- 페이지: `reportbuilder/templates/reportbuilder/intro/index.html`
- 이미지: `reportbuilder/static/reportbuilder/intro/images/`
- 업로드 HTML의 CSS·JavaScript·내용은 유지하고 이미지 주소만 Django static 태그로 연결했습니다.
- GET·HEAD 조회만 허용합니다.

운영 서버 업데이트:

```bash
git pull origin main
uv sync --frozen
uv run python manage.py collectstatic --noinput
```

Gunicorn 등 애플리케이션 서비스를 재시작하세요. 별도 DB 마이그레이션이나 /intro 전용 Nginx location은 필요하지 않습니다. 기존 Django 프록시와 /static/ 제공 설정을 사용합니다.
