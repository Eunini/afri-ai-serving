FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY services ./services
RUN chmod -R a+rX /app/services
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "services.chat.app:app", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--no-access-log"]
