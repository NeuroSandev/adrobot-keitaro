"""Структурированные логи: одна строка — один JSON-объект.

Имя события (`keitaro_retry`, `campaign_recovered`, ...) лежит в поле `event`,
остальные поля — контекст. Секреты (API-ключ, тела запросов) сюда не попадают.
"""

import json
import logging
import sys
from datetime import datetime, timezone

logger = logging.getLogger("adrobot")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def log(level: int, event: str, **fields) -> None:
    logger.log(level, event, extra={"fields": fields})


def setup_logging(level: str = "INFO") -> None:
    """Идемпотентно: повторный вызов не добавляет второй обработчик."""
    logger.setLevel(level.upper())
    if any(getattr(h, "_adrobot", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._adrobot = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
