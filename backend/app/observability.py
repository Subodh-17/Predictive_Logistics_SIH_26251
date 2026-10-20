"""Structured logging, request correlation and in-process operational counters.

* One JSON object per log line (or readable text when LOG_JSON=0) with a request id, so a user-visible error id can be matched to a log line.
* Anything that looks like a credential is masked before it is written (``security.redact`` for structured fields, a pattern filter for text).
* Counters are per process and reset on restart; they are exposed (to authenticated users only) through /api/health/detail.
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

from .security import redact

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_SECRET_IN_TEXT = re.compile(r"(?i)(password|passwd|secret|token|authorization|api[-_]?key)(\s*[=:]\s*)([^\s,;&\"']+)")
_URL_CREDENTIALS = re.compile(r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)([^@\s]+)(@)")
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def scrub(text: str) -> str:
    return _URL_CREDENTIALS.sub(r"\1***\3", _SECRET_IN_TEXT.sub(r"\1\2***", text))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"), "level": record.levelname,
               "logger": record.name, "msg": scrub(record.getMessage()), "request_id": request_id_var.get()}
        extra = {k: v for k, v in record.__dict__.items() if k not in _RESERVED and not k.startswith("_")}
        if extra:
            out.update(redact(extra))
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            out["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(out, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.msg, record.args = scrub(record.getMessage()), ()
        base = f"%(asctime)s %(levelname)s [{request_id_var.get()}] %(name)s: %(message)s"
        return scrub(logging.Formatter(base).format(record))


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_plsd", False):
            root.removeHandler(h)
    h = logging.StreamHandler()
    h._plsd = True        # type: ignore[attr-defined]
    h.setFormatter(JsonFormatter() if as_json else TextFormatter())
    root.addHandler(h)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)     # request logging is done (once, with the request id) by our middleware


class Counters:
    """Small thread-safe counter set plus a few timestamps."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.c: dict[str, int] = {}
        self.t: dict[str, float] = {}

    def inc(self, name: str, n: int = 1) -> None:
        with self._lock:
            self.c[name] = self.c.get(name, 0) + n

    def stamp(self, name: str) -> None:
        with self._lock:
            self.t[name] = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            iso = lambda v: datetime.fromtimestamp(v, timezone.utc).isoformat(timespec="seconds")
            return {"counters": dict(sorted(self.c.items())), "timestamps": {k: iso(v) for k, v in sorted(self.t.items())},
                    "process_started_at": iso(self.started_at), "uptime_seconds": int(time.time() - self.started_at)}


metrics = Counters()
