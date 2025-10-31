from datetime import datetime
import logging
import os
import sys

from pathlib import Path
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "14"))
date_str = datetime.now().strftime("%d%m%y")
LOG_FILE = LOG_DIR / f"log{date_str}.log"

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

file_handler = TimedRotatingFileHandler(
    filename=str(LOG_FILE),
    when="midnight",
    interval=1,
    backupCount=RETENTION_DAYS,
    encoding="utf-8",
    utc=False,
    delay=True,
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(
    logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

for handler in (console_handler, file_handler):
    duplicate = any(
        isinstance(existing, type(handler))
        and getattr(existing, "baseFilename", "") == getattr(
            handler, "baseFilename", None)
        for existing in root_logger.handlers
    )
    if not duplicate:
        root_logger.addHandler(handler)

for name in ("uvicorn.error", "uvicorn.access", "fastapi"):
    logger_ = logging.getLogger(name)
    logger_.setLevel(logging.INFO)
    if not any(isinstance(h, TimedRotatingFileHandler) and getattr(
        h, "baseFilename", "") == str(LOG_FILE)
               for h in logger_.handlers):
        logger_.addHandler(file_handler)

logger = logging.getLogger("mols-app")
