import logging
import json
import os
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

import gemini_client
from models import PipelineRequest, ExpandRequest, HealthResponse
from orchestrator import run_pipeline, expand_pruned_node
from prompts import STAGE_CRITIC_CONTEXT

app = FastAPI(
    title="ReqCascade",
    description="Cascading requirement generation with dual-gate validation (Multi-Provider LLM)",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
HISTORY_DIR = Path(os.path.dirname(__file__)) / ".." / "data" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(frontend_dir, "index.html"))

app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check including Gemini API connectivity."""
    connected = await gemini_client.check_connection()
    models = await gemini_client.list_models() if connected else []
    return HealthResponse(
        status="ok" if connected else "gemini_disconnected",
        gemini_connected=connected,
        available_models=models,
    )


@app.get("/api/models")
async def get_models():
    """List available Gemini models."""
    models = await gemini_client.list_models()
    return {"models": models}


@app.post("/api/run")
async def run(request: PipelineRequest):
    """Run the full cascading pipeline, returning results as an SSE stream."""
    if not request.input_text.strip():
        return {"error": "No input provided"}

    async def event_generator():
        collected_events = []
        try:
            async for event in run_pipeline(
                input_text=request.input_text,
                model=request.model,
            ):
                collected_events.append(event)
                # Save history on pipeline_complete and inject run_id into the event
                if event["event"] == "pipeline_complete":
                    run_id = _save_history(request.input_text, collected_events)
                    event["data"]["run_id"] = run_id
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
        except Exception as e:
            yield {
                "event": "pipeline_error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


@app.post("/api/run-with-file")
async def run_with_file(
    file: UploadFile = File(None),
    input_text: str = Form(""),
    model: str = Form("gemini-2.5-flash"),
):
    """Run pipeline with multipart file upload support."""
    file_content = ""
    if file:
        raw = await file.read()
        file_content = raw.decode("utf-8", errors="ignore")

    combined_input = ""
    if input_text:
        combined_input += input_text
    if file_content:
        if combined_input:
            combined_input += "\n\n"
        combined_input += file_content

    if not combined_input.strip():
        return {"error": "No input provided"}

    async def event_generator():
        collected_events = []
        try:
            async for event in run_pipeline(
                input_text=combined_input,
                model=model,
            ):
                collected_events.append(event)
                # Save history on pipeline_complete and inject run_id into the event
                if event["event"] == "pipeline_complete":
                    run_id = _save_history(combined_input, collected_events)
                    event["data"]["run_id"] = run_id
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
        except Exception as e:
            yield {
                "event": "pipeline_error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


@app.post("/api/expand")
async def expand_node(request: ExpandRequest):
    """On-demand expansion of a pruned node."""
    async def event_generator():
        try:
            async for event in expand_pruned_node(
                parent_data=request.parent_data,
                stage=request.stage,
                model=request.model,
            ):
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
        except Exception as e:
            yield {
                "event": "pipeline_error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(event_generator())


# ── History Endpoints ────────────────────────────────────────────

@app.get("/api/history")
async def list_history():
    """List all past pipeline runs."""
    runs = []
    for f in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            meta = json.loads(f.read_text())
            runs.append({
                "id": f.stem,
                "timestamp": meta.get("timestamp", f.stem),
                "input_preview": meta.get("input_text", "")[:120],
                "stats": meta.get("stats", {}),
            })
        except Exception:
            continue
    return {"runs": runs}


@app.get("/api/history/{run_id}")
async def get_history(run_id: str):
    """Fetch a specific past pipeline run."""
    path = HISTORY_DIR / f"{run_id}.json"
    if not path.exists():
        return {"error": "Run not found"}
    return json.loads(path.read_text())


@app.get("/api/history/{run_id}/export-json")
async def export_history_json(run_id: str):
    """Download a full pipeline run as a clean JSON file (includes prompts_used)."""
    path = HISTORY_DIR / f"{run_id}.json"
    if not path.exists():
        return {"error": "Run not found"}
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=f"pipeline_run_{run_id}.json",
    )


# ── History saving helper ────────────────────────────────────────

def _save_history(input_text: str, events: list[dict]) -> str:
    """Save a completed pipeline run to the history directory. Returns run_id."""
    run_id = str(int(time.time() * 1000))
    
    # Extract stats from pipeline_complete event
    stats = {}
    for ev in events:
        if ev["event"] == "pipeline_complete":
            stats = ev["data"].get("stats", {})
            break

    # Extract prompts_used per stage from node_complete events
    prompts_used: dict[str, str] = {}
    for ev in events:
        if ev["event"] == "node_complete":
            stage = ev["data"].get("stage", "")
            prompt = ev["data"].get("prompt_used", "")
            if stage and prompt and stage not in prompts_used:
                prompts_used[stage] = prompt
    
    history_data = {
        "id": run_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "used_prompt": input_text,
        "input_text": input_text,
        "prompts_used": prompts_used,
        "stage_critic_context": STAGE_CRITIC_CONTEXT,  # ← critic scoring rules per stage
        "stats": stats,
        "events": events,
    }
    
    path = HISTORY_DIR / f"{run_id}.json"
    path.write_text(json.dumps(history_data, indent=2, default=str))
    return run_id


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

