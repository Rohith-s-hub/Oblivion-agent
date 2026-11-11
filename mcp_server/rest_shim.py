"""
mcp_server/rest_shim.py — Thin REST/OpenAPI bridge in front of Oblivion's
existing MCP tool functions, for clients (like ChatGPT Custom GPT Actions)
that only speak REST + OpenAPI, not the MCP protocol.
"""
import os
from fastapi import FastAPI, Header, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel

from tools.registry import TOOL_FUNCTIONS

AUTH_TOKEN = os.environ.get("OBLIVION_AUTH_TOKEN", "")

app = FastAPI(title="Oblivion REST Shim")


def check_auth(authorization: str | None):
    if not AUTH_TOKEN:
        return  # no token configured, skip check (dev mode)
    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or missing Bearer token")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/workspace")
def get_workspace(authorization: str | None = Header(default=None)):
    check_auth(authorization)
    ws = os.environ.get("WORKSPACE_DIR", os.getcwd())
    return {"workspace": ws}


@app.get("/files")
def list_files(path: str = ".", authorization: str | None = Header(default=None)):
    check_auth(authorization)
    fn = TOOL_FUNCTIONS.get("list_dir")
    if not fn:
        raise HTTPException(status_code=500, detail="list_dir tool not registered")
    try:
        result = fn(path=path)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


class ReadFileRequest(BaseModel):
    path: str


@app.post("/file")
def read_file(body: ReadFileRequest, authorization: str | None = Header(default=None)):
    check_auth(authorization)
    fn = TOOL_FUNCTIONS.get("read_file")
    if not fn:
        raise HTTPException(status_code=500, detail="read_file tool not registered")
    try:
        result = fn(path=body.path)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
