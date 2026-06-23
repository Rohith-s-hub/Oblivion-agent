"""
tools/auto.py — Task automation pipelines

Direct bash automation without LLM calls.
Detects project type and runs the right commands.
"""
import os
import subprocess
import json
from pathlib import Path


def _run(cmd: str, cwd: str = None, timeout: int = 120) -> dict:
    """Run a shell command and return structured result."""
    workspace = cwd or os.getenv("WORKSPACE_DIR", ".")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=workspace,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timed out after {timeout}s", "code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "code": -1}


def _detect_project() -> dict:
    """Detect project type from workspace files."""
    ws = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()
    info = {"type": "unknown", "has_deps": False, "frameworks": []}

    # Node.js
    pkg = ws / "package.json"
    if pkg.exists():
        info["type"] = "node"
        info["has_deps"] = (ws / "node_modules").exists()
        try:
            data = json.loads(pkg.read_text())
            deps = set(data.get("dependencies", {}).keys())
            deps.update(data.get("devDependencies", {}).keys())
            if "react" in deps:
                info["frameworks"].append("react")
            if "vue" in deps:
                info["frameworks"].append("vue")
            if "next" in deps:
                info["frameworks"].append("nextjs")
            if "vite" in deps:
                info["frameworks"].append("vite")
            if "tailwindcss" in deps:
                info["frameworks"].append("tailwind")
            info["scripts"] = list(data.get("scripts", {}).keys())
        except Exception:
            info["scripts"] = []
        return info

    # Python
    if (ws / "pyproject.toml").exists() or (ws / "requirements.txt").exists():
        info["type"] = "python"
        info["has_deps"] = (ws / ".venv").exists() or (ws / "venv").exists()
        if (ws / "manage.py").exists():
            info["frameworks"].append("django")
        if any(ws.rglob("*fastapi*")):
            info["frameworks"].append("fastapi")
        return info

    return info


def auto_build() -> str:
    """Detect project type and run build pipeline."""
    proj = _detect_project()
    steps = []

    if proj["type"] == "node":
        # Install deps if needed
        if not proj["has_deps"]:
            steps.append(("npm install", _run("npm install")))
        # Build
        if "build" in proj.get("scripts", []):
            steps.append(("npm run build", _run("npm run build")))
        else:
            steps.append(("skip build", {"ok": True, "stdout": "No build script found", "stderr": "", "code": 0}))

    elif proj["type"] == "python":
        if not proj["has_deps"]:
            if Path(os.getenv("WORKSPACE_DIR", "."), "requirements.txt").exists():
                steps.append(("pip install -r requirements.txt", _run("pip install -r requirements.txt")))
            elif Path(os.getenv("WORKSPACE_DIR", "."), "pyproject.toml").exists():
                steps.append(("pip install -e .", _run("pip install -e .")))
    else:
        return "Could not detect project type. No package.json or pyproject.toml found."

    # Format results
    lines = [f"Project: {proj['type']} ({', '.join(proj.get('frameworks', [])) or 'generic'})"]
    for cmd, result in steps:
        icon = "OK" if result["ok"] else "FAIL"
        lines.append(f"  [{icon}] {cmd}")
        if not result["ok"] and result["stderr"]:
            lines.append(f"       {result['stderr'][:200]}")

    return "\n".join(lines)


def auto_test() -> str:
    """Detect test framework and run tests."""
    proj = _detect_project()
    steps = []

    if proj["type"] == "node":
        if "test" in proj.get("scripts", []):
            steps.append(("npm test", _run("npm test", timeout=60)))
        elif "vitest" in str(proj.get("scripts", {})):
            steps.append(("npx vitest run", _run("npx vitest run", timeout=60)))
        else:
            return "No test script found in package.json"

    elif proj["type"] == "python":
        # Try pytest first, then unittest
        r = _run("python -m pytest --tb=short -q", timeout=60)
        if r["code"] != 127:
            steps.append(("pytest", r))
        else:
            steps.append(("python -m unittest discover", _run("python -m unittest discover", timeout=60)))
    else:
        return "Could not detect project type."

    lines = ["Test Results:"]
    for cmd, result in steps:
        icon = "PASS" if result["ok"] else "FAIL"
        lines.append(f"  [{icon}] {cmd}")
        if result["stdout"]:
            for line in result["stdout"].split("\n")[-10:]:
                lines.append(f"    {line}")
        if not result["ok"] and result["stderr"]:
            lines.append(f"    stderr: {result['stderr'][:200]}")

    return "\n".join(lines)


def auto_serve() -> str:
    """Install deps + start dev server + health check."""
    proj = _detect_project()

    if proj["type"] == "node":
        # Install if needed
        if not proj["has_deps"]:
            r = _run("npm install")
            if not r["ok"]:
                return f"npm install failed: {r['stderr'][:200]}"

        # Find dev command
        dev_cmd = None
        for cmd_name in ["dev", "start", "serve"]:
            if cmd_name in proj.get("scripts", []):
                dev_cmd = f"npm run {cmd_name}"
                break
        if not dev_cmd:
            dev_cmd = "npx vite --host"

        # Start server in background
        try:
            from tools.bash import start_server
            result = start_server(command=dev_cmd, port=3000, wait_seconds=8)
            return f"Server started!\n{result}\n\nOpen http://localhost:3000 in your browser."
        except Exception as e:
            return f"Could not start server: {e}"

    elif proj["type"] == "python":
        if "django" in proj.get("frameworks", []):
            return _run("python manage.py runserver 0.0.0.0:8000 &")["stdout"] or "Django server starting on :8000"
        elif "fastapi" in proj.get("frameworks", []):
            return _run("uvicorn main:app --host 0.0.0.0 --port 8000 &")["stdout"] or "FastAPI starting on :8000"

    return "Could not detect how to serve this project."


def auto_clean() -> str:
    """Remove build artifacts and caches."""
    ws = Path(os.getenv("WORKSPACE_DIR", ".")).resolve()
    cleaned = []

    targets = [
        ("node_modules", "rm -rf node_modules"),
        ("dist", "rm -rf dist"),
        ("build", "rm -rf build"),
        (".next", "rm -rf .next"),
        ("__pycache__", "find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null"),
        (".pytest_cache", "rm -rf .pytest_cache"),
        ("*.pyc", "find . -name '*.pyc' -delete 2>/dev/null"),
    ]

    for name, cmd in targets:
        target_path = ws / name
        if target_path.exists() or name.startswith("*"):
            r = _run(cmd)
            if r["ok"]:
                cleaned.append(name)

    if cleaned:
        return "Cleaned: " + ", ".join(cleaned)
    return "Nothing to clean."


def auto_check() -> str:
    """Run linting and type checking."""
    proj = _detect_project()
    results = []

    if proj["type"] == "node":
        if "lint" in proj.get("scripts", []):
            r = _run("npm run lint", timeout=30)
            results.append(("lint", r))
        if "typecheck" in proj.get("scripts", []):
            r = _run("npm run typecheck", timeout=30)
            results.append(("typecheck", r))
        elif (Path(os.getenv("WORKSPACE_DIR", ".")) / "tsconfig.json").exists():
            r = _run("npx tsc --noEmit", timeout=30)
            results.append(("tsc --noEmit", r))

    elif proj["type"] == "python":
        r = _run("python -m py_compile *.py", timeout=15)
        results.append(("syntax check", r))

    if not results:
        return "No lint/check tools detected."

    lines = ["Check Results:"]
    for name, r in results:
        icon = "PASS" if r["ok"] else "FAIL"
        lines.append(f"  [{icon}] {name}")
        if not r["ok"]:
            lines.append(f"    {r['stderr'][:200] or r['stdout'][:200]}")

    return "\n".join(lines)
