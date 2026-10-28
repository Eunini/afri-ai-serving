FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements-speech.lock ./
RUN pip install --no-cache-dir -r requirements-speech.lock
COPY services ./services
COPY LICENSE ./LICENSE
RUN chmod -R a+rX /app/services
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app
USER 10001
ENV HF_HOME=/tmp/huggingface
EXPOSE 8000
CMD ["uvicorn", "services.speech.app:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--no-access-log"]
