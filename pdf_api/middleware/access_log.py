import json
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _get_real_ip(request: Request) -> str:
    # Cloudflare tunnel passes real client IP in CF-Connecting-IP
    for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _build_logger(log_dir: str, retention_days: int) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("access")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = TimedRotatingFileHandler(
            filename=str(Path(log_dir) / "access.log"),
            when="midnight",
            backupCount=retention_days,
            encoding="utf-8",
            utc=True,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    return logger


class AccessLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, log_dir: str, retention_days: int):
        super().__init__(app)
        self._logger = _build_logger(log_dir, retention_days)

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)

        self._logger.info(json.dumps({
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ip": _get_real_ip(request),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "ua": request.headers.get("user-agent", ""),
            "source": "api",
        }))

        return response
