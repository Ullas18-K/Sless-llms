"""
Purpose: FastAPI wrapper around Ollama for chat inference, health checks, and Prometheus metrics.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

load_dotenv()

APP_NAME = "serverless-llm-api"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "tinyllama")
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(APP_NAME)

app = FastAPI(title=APP_NAME, version="1.0.0")

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
INFERENCE_DURATION = Histogram(
    "inference_duration_seconds",
    "LLM inference duration in seconds",
    ["model", "status"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)


class ChatRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Prompt to send to the model")
    model: str = Field(default=DEFAULT_MODEL, description="Ollama model name")
    stream: bool = Field(default=False, description="Stream response as NDJSON")
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT, ge=1, le=300)


class ChatResponse(BaseModel):
    model: str
    response: str
    latency_ms: float


@app.middleware("http")
async def request_metrics_and_logging(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        HTTP_REQUESTS.labels(
            method=request.method,
            path=request.url.path,
            status_code=str(status_code),
        ).inc()
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "latency_ms": round(latency_ms, 2),
                }
            )
        )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "model": DEFAULT_MODEL}


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)


async def _post_ollama(payload: dict[str, Any], timeout_seconds: float) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            return await client.post(f"{OLLAMA_URL}/api/generate", json=payload)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Ollama is not reachable") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama request timed out") from exc


async def _stream_ollama(payload: dict[str, Any], timeout_seconds: float) -> AsyncIterator[str]:
    start = time.perf_counter()
    bytes_sent = 0
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    message = body.decode("utf-8", errors="ignore")
                    raise HTTPException(status_code=502, detail=f"Ollama error: {message}")

                async for line in response.aiter_lines():
                    if line:
                        bytes_sent += len(line)
                        yield f"{line}\n"

                INFERENCE_DURATION.labels(model=payload["model"], status="success").observe(
                    time.perf_counter() - start
                )
    except HTTPException:
        INFERENCE_DURATION.labels(model=payload["model"], status="error").observe(time.perf_counter() - start)
        raise
    except httpx.ConnectError as exc:
        INFERENCE_DURATION.labels(model=payload["model"], status="error").observe(time.perf_counter() - start)
        raise HTTPException(status_code=503, detail="Ollama is not reachable") from exc
    except httpx.TimeoutException as exc:
        INFERENCE_DURATION.labels(model=payload["model"], status="timeout").observe(time.perf_counter() - start)
        raise HTTPException(status_code=504, detail="Ollama request timed out") from exc
    finally:
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "stream_completed",
                    "model": payload["model"],
                    "bytes_sent": bytes_sent,
                }
            )
        )


@app.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat(body: ChatRequest):
    payload = {
        "model": body.model,
        "prompt": body.prompt,
        "stream": body.stream,
    }

    if body.stream:
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "chat_stream_started",
                    "model": body.model,
                    "status_code": 200,
                }
            )
        )
        return StreamingResponse(
            _stream_ollama(payload=payload, timeout_seconds=body.timeout_seconds),
            media_type="application/x-ndjson",
        )

    start = time.perf_counter()
    response = await _post_ollama(payload=payload, timeout_seconds=body.timeout_seconds)
    elapsed = time.perf_counter() - start

    if response.status_code >= 400:
        INFERENCE_DURATION.labels(model=body.model, status="error").observe(elapsed)
        detail = response.text.strip() or "Unknown Ollama error"
        logger.error(
            json.dumps(
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "chat_failed",
                    "model": body.model,
                    "status_code": response.status_code,
                    "latency_ms": round(elapsed * 1000, 2),
                }
            )
        )
        if "model" in detail.lower() and "not found" in detail.lower():
            raise HTTPException(status_code=404, detail="Model not loaded in Ollama")
        raise HTTPException(status_code=502, detail=f"Ollama error: {detail}")

    data = response.json()
    if "response" not in data:
        INFERENCE_DURATION.labels(model=body.model, status="error").observe(elapsed)
        raise HTTPException(status_code=502, detail="Unexpected Ollama response format")

    INFERENCE_DURATION.labels(model=body.model, status="success").observe(elapsed)
    logger.info(
        json.dumps(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "chat_completed",
                "model": body.model,
                "status_code": 200,
                "latency_ms": round(elapsed * 1000, 2),
            }
        )
    )
    return ChatResponse(
        model=body.model,
        response=data.get("response", ""),
        latency_ms=round(elapsed * 1000, 2),
    )


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
