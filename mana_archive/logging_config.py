"""Centralized logging configuration using RotatingFileHandler."""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "mana_archive.log")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 3


def configure_logging() -> None:
    """Configure the root logger with a RotatingFileHandler and a StreamHandler."""
    os.makedirs(LOG_DIR, exist_ok=True)

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    root_logger.setLevel(logging.DEBUG)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named child logger, ensuring root is configured first."""
    configure_logging()
    return logging.getLogger(name)
