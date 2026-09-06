"""FastAPI UI + API layer for the LinkedIn Job Source Agent.

All pipeline logic lives in job_agent/ (untouched by this migration). This
module only adapts that synchronous, Playwright-driven pipeline to an async
web server: single calls run in a worker thread via asyncio.to_thread, the
streaming endpoint bridges the pipeline's sync generator to SSE via a
background thread + queue, and /batch bounds concurrency with a semaphore.
"""

import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from job_agent.pipeline import resolve_job_listing_url, run_pipeline_stages, summarize

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
BATCH_CONCURRENCY = 5

app = FastAPI(title="LinkedIn Job Source Agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ResolveRequest(BaseModel):
    url: str


class BatchRequest(BaseModel):
    urls: list[str]


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/resolve")
async def resolve(payload: ResolveRequest) -> dict:
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    return await asyncio.to_thread(resolve_job_listing_url, url)


@app.get("/resolve/stream")
async def resolve_stream(url: str) -> EventSourceResponse:
    url = url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    async def event_generator() -> AsyncIterator[dict[str, Any]]:
        stage_queue: "queue.Queue" = queue.Queue()
        sentinel = object()

        def worker() -> None:
            try:
                for event in run_pipeline_stages(url):
                    stage_queue.put(event)
            finally:
                stage_queue.put(sentinel)

        threading.Thread(target=worker, daemon=True).start()

        loop = asyncio.get_event_loop()
        events = []
        while True:
            event = await loop.run_in_executor(None, stage_queue.get)
            if event is sentinel:
                break
            events.append(event)
            yield {"event": event.stage, "data": json.dumps(event.as_dict())}
            if event.status == "error":
                break

        yield {"event": "done", "data": json.dumps(summarize(url, events))}

    return EventSourceResponse(event_generator())


@app.post("/batch")
async def batch(payload: BatchRequest) -> dict:
    urls = [url.strip() for url in payload.urls if url.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="urls must be a non-empty list")

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def bounded_resolve(url: str) -> dict:
        async with semaphore:
            return await asyncio.to_thread(resolve_job_listing_url, url)

    results = await asyncio.gather(*(bounded_resolve(url) for url in urls))

    total = len(results)
    succeeded = sum(1 for result in results if result["status"] == "success")
    avg_elapsed_ms = int(sum(result["elapsed_ms"] for result in results) / total) if total else 0

    return {
        "results": results,
        "summary": {
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "success_rate": round(succeeded / total * 100, 1) if total else 0.0,
            "avg_elapsed_ms": avg_elapsed_ms,
        },
    }
