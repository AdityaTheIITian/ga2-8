import json
import logging
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

EMAIL = "23f1003148@ds.study.iitm.ac.in"
START = time.monotonic()

# prometheus_client appends "_total", so this is exposed as http_requests_total
REQUESTS = Counter("http_requests", "Total HTTP requests to any endpoint")

LOGS = deque(maxlen=1000)  # in-memory ring buffer behind /logs/tail

stdout_logger = logging.getLogger("app")
stdout_logger.setLevel(logging.INFO)
_h = logging.StreamHandler(sys.stdout)
_h.setFormatter(logging.Formatter("%(message)s"))
stdout_logger.addHandler(_h)
stdout_logger.propagate = False

app = FastAPI()


def record(level: str, request: Request, request_id: str, status: int, duration: float):
    entry = {
        "level": level,
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": request.url.path,
        "request_id": request_id,
        "method": request.method,
        "status": status,
        "duration_s": round(duration, 6),
    }
    LOGS.append(entry)
    stdout_logger.info(json.dumps(entry))  # structured JSON line on stdout


@app.middleware("http")
async def instrument(request: Request, call_next):
    REQUESTS.inc()  # every request to any endpoint, including /metrics itself
    request_id = str(uuid.uuid4())
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        record("error", request, request_id, 500, time.perf_counter() - start)
        raise
    response.headers["X-Request-ID"] = request_id
    record("info", request, request_id, response.status_code, time.perf_counter() - start)
    return response


@app.get("/work")
def work(n: int = Query(..., ge=0)):
    acc = 0
    for i in range(min(n, 100_000)):  # cheap real work, capped so n can't hang the server
        acc += i * i
    return {"email": EMAIL, "done": n}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "uptime_s": float(time.monotonic() - START)}


@app.get("/logs/tail")
def logs_tail(limit: int = Query(10, ge=1, le=1000)):
    return list(LOGS)[-limit:]
