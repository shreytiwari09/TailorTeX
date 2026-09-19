# TailorTeX: one image with the web app, the API, TeX Live and poppler.
#   docker compose up --build     then open http://localhost:8000

# 1) Build the frontend
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# 2) The app: Python, TeX Live (pdfLaTeX, XeLaTeX, LuaLaTeX) and poppler for PDF text
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TAILORTEX_DATA_DIR=/data \
    TAILORTEX_TEX_AUTOINSTALL=0 \
    PORT=8000

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra \
      texlive-fonts-recommended texlive-xetex texlive-luatex lmodern cm-super \
      poppler-utils \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc/* /usr/share/man/*

RUN useradd --create-home --uid 10001 app && mkdir -p /data /opt/fastembed && chown app /data /opt/fastembed
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/tailortex backend/tailortex
COPY --from=web /web/dist frontend/dist

USER app
# Download the small embedding model now (about 130 MB), so matching by meaning works without a runtime download.
RUN python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warm up'])); print('embedding model ready')"
# Compile the default template once, to check TeX works and warm the font caches.
RUN cd backend && python -c "from pathlib import Path; from tailortex.compile.compile import compile_latex; r = compile_latex(Path('tailortex/templates/jake/resume.tex').read_text()); assert r.ok, r.errors; print('TeX OK:', r.pages, 'page')"

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
CMD ["sh", "-c", "cd backend && exec uvicorn tailortex.api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
