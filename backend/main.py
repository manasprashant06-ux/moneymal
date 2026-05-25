"""
Hybrid Sentinel — FastAPI Backend
Async Job Architecture: Upload returns job_id immediately.
Engine runs in a background thread pool (full accuracy, no shortcuts).
Poll /api/result/{job_id} for the result.
"""

import io
import json
import os
import uuid
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from backend.engine import ForensicsEngine

# ---- In-memory job store ------------------------------------------------- #
# Stores job results keyed by job_id. Lightweight for a local app.
_jobs: dict[str, dict] = {}

# Thread pool: engine runs here so FastAPI event loop never blocks
_executor = ThreadPoolExecutor(max_workers=2)


def _run_engine(job_id: str, df: pd.DataFrame) -> None:
    """Runs the full forensics engine in a background thread. No accuracy shortcuts."""
    try:
        _jobs[job_id]["status"] = "running"
        engine = ForensicsEngine()
        engine.load_data(df)
        result = engine.run_all()
        graph_data = engine.get_graph_data()
        _jobs[job_id] = {
            "status": "done",
            "result": json.loads(json.dumps(result, default=str)),
            "graph":  json.loads(json.dumps(graph_data, default=str)),
        }
    except Exception as e:
        _jobs[job_id] = {"status": "error", "detail": str(e)}


# ---- FastAPI App ---------------------------------------------------------- #
app = FastAPI(
    title="Hybrid Sentinel API",
    description="Money Muling Detection Engine — Async Job Architecture",
    version="6.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "engine": "Hybrid Sentinel v6 (Async)"}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    """
    Accept CSV upload and immediately return a job_id.
    The engine runs in a background thread — no timeout possible.
    Poll /api/result/{job_id} for progress and results.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    try:
        content = await file.read()
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse CSV: {e}")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued"}

    # Submit to thread pool — returns immediately, no blocking
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_engine, job_id, df)

    return JSONResponse(content={"job_id": job_id, "status": "queued"})


@app.get("/api/result/{job_id}")
async def get_result(job_id: str):
    """
    Poll this endpoint after submitting an analysis job.
    Returns: status = 'queued' | 'running' | 'done' | 'error'
    When status == 'done', result and graph are included.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JSONResponse(content=job)


@app.get("/api/jobs")
async def list_jobs():
    """List all current job IDs and their statuses."""
    return {"jobs": {jid: j.get("status") for jid, j in _jobs.items()}}


# ---- Serve frontend static build ------------------------------------------ #
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(FRONTEND_DIST, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=False)
