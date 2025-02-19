FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml requirements-speech.lock ./
COPY services ./services
RUN chmod -R a+rX /app/services
RUN pip install --no-cache-dir -r requirements-speech.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app
USER 10001
ENV HF_HOME=/tmp/huggingface
EXPOSE 8000
CMD ["uvicorn", "services.speech.app:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--no-access-log"]
