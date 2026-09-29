# CityPulse — single-container production image.
# Stage 1 builds the React dashboard; stage 2 runs FastAPI (API + WebSocket)
# which also serves the built frontend — one origin, one public URL.
#
# Path note: backend/main.py resolves the SPA directory as ../frontend/dist
# relative to main.py, so with the app at /app/main.py the dist must land at
# /frontend/dist (NOT /app/frontend/dist).

# ---------- stage 1: build the frontend ----------
FROM node:20-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: runtime ----------
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend-build /build/dist /frontend/dist

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CITYPULSE_ALLOWED_ORIGINS=*
# Render/Railway/Fly inject PORT; default to 8000 for local runs of the image.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
