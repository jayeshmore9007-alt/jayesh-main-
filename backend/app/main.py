import os
import sqlite3
import time
from pathlib import Path
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "analytics.db"

def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            input_tokens INTEGER DEFAULT 0,
            cached_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            latency_ms REAL DEFAULT 0
        )
        """)

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(title="CIPHERX Ultimate AI", lifespan=lifespan)

class ChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=12000)

@app.get("/")
def home():
    return {"app": "CIPHERX Ultimate AI", "status": "online"}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/cache/config")
def cache_config():
    return {
        "mode": "automatic",
        "requested_ttl": "30m",
        "note": "Actual caching depends on model/API support."
    }

@app.post("/api/chat")
async def chat(body: ChatInput):
    key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()

    if not key:
        raise HTTPException(503, "OPENAI_API_KEY missing in backend/.env")

    if not model:
        raise HTTPException(503, "OPENAI_MODEL missing in backend/.env")

    payload = {
        "model": model,
        "store": False,
        "instructions": (
            "You are CIPHERX Ultimate AI. Help with research, coding, "
            "defensive security, automation, crypto intelligence and QA. "
            "Require approval before consequential actions. "
            "Never claim an action was performed unless verified."
        ),
        "input": body.question
    }

    start = time.perf_counter()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        try:
            message = e.response.json()["error"]["message"]
        except Exception:
            message = "OpenAI API request failed"
        raise HTTPException(502, message[:1000])
    except httpx.RequestError:
        raise HTTPException(502, "OpenAI connection failed")

    latency = round((time.perf_counter() - start) * 1000, 2)
    usage = data.get("usage") or {}
    details = usage.get("input_tokens_details") or {}

    with sqlite3.connect(DB) as db:
        db.execute("""
        INSERT INTO usage(input_tokens,cached_tokens,output_tokens,latency_ms)
        VALUES(?,?,?,?)
        """, (
            usage.get("input_tokens", 0),
            details.get("cached_tokens", 0),
            usage.get("output_tokens", 0),
            latency
        ))

    answer = "\n".join(
        content.get("text", "")
        for item in data.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )

    return {
        "ok": True,
        "model": data.get("model", model),
        "answer": answer,
        "usage": usage,
        "latency_ms": latency
    }

@app.get("/api/analytics")
def analytics():
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("""
        SELECT COUNT(*) requests,
        COALESCE(SUM(input_tokens),0) input_tokens,
        COALESCE(SUM(cached_tokens),0) cached_tokens,
        COALESCE(SUM(output_tokens),0) output_tokens,
        COALESCE(AVG(latency_ms),0) avg_latency_ms
        FROM usage
        """).fetchone()
    return {"analytics": dict(row)}
