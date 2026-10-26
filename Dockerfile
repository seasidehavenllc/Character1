FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data /workspace && useradd --create-home --uid 10001 corvis && chown -R corvis:corvis /app /data /workspace
USER corvis
EXPOSE 8765
CMD ["python", "-m", "corvis", "--config", "/app/config.docker.yaml", "web", "--no-browser"]
