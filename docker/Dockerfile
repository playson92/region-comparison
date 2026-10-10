FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-deps --no-build-isolation . && useradd --create-home --uid 10001 region
COPY app.py ./
COPY config ./config
COPY sql ./sql
COPY data/sample ./data/sample
COPY .streamlit ./.streamlit
ENV REGION_PROJECT_ROOT=/app
USER region
EXPOSE 8501
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"
CMD ["python", "-m", "streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.headless=true"]
