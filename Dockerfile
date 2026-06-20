FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    RAPFI_HOST=0.0.0.0 \
    RAPFI_PORT=8787 \
    RAPFI_IDLE_SLEEP_SECONDS=180 \
    RAPFI_MAX_ACTIVE_ENGINES=3 \
    RAPFI_ENGINE_DIR=Rapfi-engine \
    RAPFI_ENGINE_EXE=Rapfi-engine/pbrain-rapfi-linux-clang-avx2 \
    RAPFI_STORAGE_DIR=games \
    RAPFI_DEFAULT_LEVEL=2

COPY api ./api
COPY Rapfi-engine ./Rapfi-engine
COPY RAPFI_API.md ./

RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /app/Rapfi-engine/pbrain-rapfi-linux-clang-* \
    && mkdir -p /app/games

EXPOSE 8787
VOLUME ["/app/games"]

CMD ["python", "api/server.py"]
