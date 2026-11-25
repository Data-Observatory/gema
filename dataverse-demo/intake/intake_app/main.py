"""Process entry point: ``uvicorn --factory intake_app.main:build_app``."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI

from intake_app.config import Settings
from intake_app.dataverse import DataverseClient
from intake_app.errors import ConfigError
from intake_app.gema_runner import GemaRunner
from intake_app.processor import BatchProcessor, Defaults
from intake_app.store import Store
from intake_app.web import create_app

logger = logging.getLogger("intake_app")


def _setup_logging(settings: Settings) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = RotatingFileHandler(
            settings.log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(fmt)
        root.addHandler(rotating)
    except OSError as exc:
        logger.warning("cannot write %s (%s); logging to stderr only", settings.log_file, exc)
    # The OpenAI/httpx clients log full URLs and headers at INFO; keep them quieter.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_app() -> FastAPI:
    try:
        settings = Settings.from_env()
        _setup_logging(settings)
        runner = GemaRunner.from_files(
            settings.gema_config,
            settings.export_config,
            preflight=settings.preflight_url,
            allow_private_urls=settings.allow_private_urls,
        )
    except ConfigError as exc:
        sys.stderr.write(f"intake: configuration error: {exc}\n")
        raise SystemExit(2) from exc

    store = Store(settings.db_path)
    store.init()
    recovered = store.recover_stale()
    if recovered:
        logger.warning("recovered %d record(s) left in 'processing' by a restart", recovered)
    if not settings.dataverse_token:
        logger.warning("DATAVERSE_API_TOKEN is empty: the page works but Process is disabled")

    dataverse = DataverseClient(
        base_url=settings.dataverse_url,
        public_url=settings.dataverse_public_url,
        token=settings.dataverse_token,
        collection_alias=settings.collection_alias,
    )
    processor = BatchProcessor(
        store,
        runner,
        dataverse,
        Defaults(settings.default_contact_email, settings.default_contact_name),
        workers=settings.workers,
        record_timeout=settings.record_timeout,
        retry_delay=settings.retry_delay,
    )
    logger.info(
        "intake ready: collection=%s workers=%d timeout=%ds max_records=%d db=%s",
        settings.collection_alias,
        settings.workers,
        settings.record_timeout,
        settings.max_records,
        settings.db_path,
    )
    return create_app(settings, store, processor, can_publish=bool(settings.dataverse_token))
