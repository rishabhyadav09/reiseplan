FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

ARG BUILD_SHA=dev
ENV BUILD_SHA=$BUILD_SHA

COPY backend/pyproject.toml .
RUN pip install fastapi "uvicorn[standard]" httpx pydantic redis

COPY backend/app ./app
COPY web /web

# Railway, Fly and Render all inject PORT. Hardcoding 8000 builds fine and
# then fails the health check, which is a maddening thing to debug.
ENV PORT=8000
EXPOSE 8000
CMD ["sh","-c","exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
