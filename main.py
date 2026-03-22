"""
main.py — FastAPI server
GET  /       → serves the UI
POST /audit  → runs the agentic audit
GET  /health → status check
"""

import sys, asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from ai_engine import run_agent_audit

app = FastAPI(title="Page Audit Agent v3")
app.mount("/static", StaticFiles(directory="static"), name="static")


class AuditRequest(BaseModel):
    url: str


@app.get("/")
def serve_ui():
    return FileResponse("static/index.html")


@app.post("/audit")
def audit(req: AuditRequest):
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        result = run_agent_audit(url)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Audit failed: {e}")

    # Strip internal content sample before sending to UI
    if "metrics" in result and isinstance(result["metrics"], dict):
        result["metrics"].pop("_content_sample", None)

    return result


@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("OPENROUTER_MODEL", "not configured")}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
