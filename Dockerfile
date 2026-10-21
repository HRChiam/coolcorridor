# Alternative to Community Cloud. Target Python 3.13; pin a tested image digest
# before publication. Container/Linux execution has to be verified on the target.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8501
WORKDIR /app
COPY requirements.txt requirements-person3-lock.txt ./
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY deployment_package.py deployment_check.py streamlit_app.py ./
COPY deployment/ ./deployment/
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN python -B deployment_package.py
USER appuser
EXPOSE 8501
HEALTHCHECK --interval=30s --start-period=60s --timeout=5s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8501')+'/_stcore/health',timeout=4)"
CMD ["sh", "-c", "exec python -B -m streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=${PORT:-8501}"]
