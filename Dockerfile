# eln_server (Flask + gunicorn). Build context: the repository root.
# config.yaml and secrets.yaml are not baked in: mount them at run time (see deploy/compose.yaml).
FROM python:3.11-slim-bookworm

# system libraries the Python packages load at run time:
#   WeasyPrint (label PDFs): Pango + DejaVu fonts (labels ask for Courier New -> DejaVu Sans Mono)
#   RDKit (structure images): libXrender, libXext
#   tzdata: "Opened" dates are stamped in lab time (TZ below)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core libxrender1 libxext6 tzdata \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/New_York

WORKDIR /app

# dependencies first: this layer is cached and only rebuilt when they change.
# constraints.txt pins the versions the test suite was run against.
COPY requirements.txt constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

# then the application code
COPY . .

# run as a non-root user with uid 1000, so the mounted config.yaml/secrets.yaml can
# stay owned by the server's admin user. The app writes label PDFs to static/; the home
# folder holds gunicorn's control socket and the font cache.
RUN useradd --uid 1000 --create-home eln && chown eln:eln /app/static
USER eln
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/ping', timeout=4).status==200 else 1)"

# 1 worker, as on the old server (~160 MB each). --timeout matches the timer client's
# 600 s wait, so a long peroxide check isn't killed halfway.
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "--timeout", "600", "--access-logfile", "-", "app:app"]
