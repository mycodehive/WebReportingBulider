FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_SYNC=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN useradd --create-home --uid 10001 webreport && mkdir /data && chown webreport:webreport /data
ENV WEBREPORT_BASE_DIR=/data
USER webreport
EXPOSE 8000
CMD ["sh", "-c", "uv run python manage.py collectstatic --noinput && uv run gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120"]
