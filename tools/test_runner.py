"""
tools/test_runner.py - Intelligent test runner for Oblivion.

Detects test framework, runs tests, parses failures into
structured output that Meera can act on directly.

Supports:
  - pytest (Python)
  - unittest (Python)
  - jest (JavaScript/TypeScript)
  - vitest (Vite projects)
  - npm test / yarn test
  - go test
  - cargo test (Rust)
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


def _get_workspace() -> Path:
    return Path(os.getenv("WORKSPACE_DIR", ".")).expanduser().resolve()


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[int, str, str]:
    """Run command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Tests timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


def detect_test_framework(workspace: Path = None) -> dict:
    """
    Auto-detect the test framework used in this project.
    Returns {framework, command, config_file}
    """
    ws = workspace or _get_workspace()

    # Check package.json for JS frameworks
    pkg_json = ws / "package.json"
    if pkg_json.exists():
        try:
            import json
            pkg = json.loads(pkg_json.read_text())
            scripts = pkg.get("scripts", {})
            deps = {
                **pkg.get("dependencies", {}),
                **pkg.get("devDependencies", {}),
            }

            if "vitest" in deps:
                return {
                    "framework": "vitest",
                    "command": ["npx", "vitest", "run", "--reporter=verbose"],
                    "config": "vitest.config.ts",
                }
            if "jest" in deps or "@jest/core" in deps:
                return {
                    "framework": "jest",
                    "command": ["npx", "jest", "--no-coverage", "--verbose"],
                    "config": "jest.config.js",
                }
            if "test" in scripts:
                return {
                    "framework": "npm-test",
                    "command": ["npm", "test", "--", "--watchAll=false"],
                    "config": "package.json",
                }
        except Exception:
            pass

    # Check for pytest
    for cfg in ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"]:
        if (ws / cfg).exists():
            return {
                "framework": "pytest",
                "command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
                "config": cfg,
            }

    # Check for Python test files
    py_tests = list(ws.rglob("test_*.py")) + list(ws.rglob("*_test.py"))
    if py_tests:
        return {
            "framework": "pytest",
            "command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
            "config": "auto-detected",
        }

    # Go
    if (ws / "go.mod").exists():
        return {
            "framework": "go-test",
            "command": ["go", "test", "./...", "-v"],
            "config": "go.mod",
        }

    # Rust
    if (ws / "Cargo.toml").exists():
        return {
            "framework": "cargo-test",
            "command": ["cargo", "test"],
            "config": "Cargo.toml",
        }

    return {
        "framework": "unknown",
        "command": [],
        "config": "",
    }


def _parse_pytest_failures(output: str) -> list[dict]:
    """Extract structured failure info from pytest output."""
    failures = []
    current = None

    for line in output.split("\n"):
        # Start of a failure block: FAILED test_file.py::test_name
        m = re.match(r"FAILED\s+([\w/\\.-]+)::(\w+)", line)
        if m:
            if current:
                failures.append(current)
            current = {
                "file": m.group(1),
                "test": m.group(2),
                "error": "",
                "lines": [],
            }
            continue

        # Error type line: E   AssertionError: ...
        if current and line.startswith("E "):
            current["error"] += line[2:].strip() + " "
            continue

        # File + line reference
        if current and re.match(r"\s+[\w/\\.-]+\.py:\d+", line):
            current["lines"].append(line.strip())

    if current:
        failures.append(current)

    # Clean up
    for f in failures:
        f["error"] = f["error"].strip()[:300]
    return failures


def _parse_jest_failures(output: str) -> list[dict]:
    """Extract structured failure info from jest output."""
    failures = []
    current = None

    for line in output.split("\n"):
        # ● test suite name › test name
        m = re.match(r"\s+●\s+(.+)", line)
        if m:
            if current:
                failures.append(current)
            current = {
                "test": m.group(1).strip(),
                "file": "",
                "error": "",
                "lines": [],
            }
            continue

        if current:
            # Error message lines
            if "Expected:" in line or "Received:" in line or "Error:" in line:
                current["error"] += line.strip() + " "
            # File reference
            m2 = re.match(r"\s+at .+ \((.+\.(?:js|ts|jsx|tsx)):(\d+)", line)
            if m2:
                current["file"] = m2.group(1)
                current["lines"].append(f"{m2.group(1)}:{m2.group(2)}")

    if current:
        failures.append(current)

    for f in failures:
        f["error"] = f["error"].strip()[:300]
    return failures


def run_tests(path: str = "", framework: str = "auto") -> str:
    """
    Run the test suite and return structured results.

    path: specific test file or directory (empty = all tests)
    framework: auto | pytest | jest | vitest | npm

    Returns pass/fail summary + structured failure details
    that Meera can act on to fix failing tests.
    """
    ws = _get_workspace()

    # Detect framework
    if framework == "auto":
        detected = detect_test_framework(ws)
    else:
        framework_map = {
            "pytest": {
                "framework": "pytest",
                "command": ["python", "-m", "pytest", "-v", "--tb=short", "--no-header"],
            },
            "jest": {
                "framework": "jest",
                "command": ["npx", "jest", "--no-coverage", "--verbose"],
            },
            "vitest": {
                "framework": "vitest",
                "command": ["npx", "vitest", "run", "--reporter=verbose"],
            },
            "npm": {
                "framework": "npm-test",
                "command": ["npm", "test", "--", "--watchAll=false"],
            },
        }
        detected = framework_map.get(framework, detect_test_framework(ws))

    if not detected["command"]:
        return (
            "No test framework detected in this workspace.\n\n"
            "Supported: pytest, jest, vitest, npm test, go test, cargo test\n\n"
            "To set up tests:\n"
            "  Python: pip install pytest && create test_*.py files\n"
            "  JS/TS:  npm install --save-dev jest && add test script to package.json"
        )

    cmd = detected["command"].copy()

    # Add specific path if provided
    if path:
        cmd.append(path)

    lines = [
        f"🧪 Running {detected['framework']} tests...",
        f"   Command: {' '.join(cmd)}",
        f"   Workspace: {ws}",
        "",
    ]

    returncode, stdout, stderr = _run(cmd, ws, timeout=120)
    output = stdout + "\n" + stderr

    # Parse results
    framework_name = detected["framework"]

    if returncode == 0:
        # All passed
        lines.append("✅ ALL TESTS PASSED")
        lines.append("")

        # Extract summary line
        for line in output.split("\n"):
            if re.search(r"\d+ passed", line, re.IGNORECASE):
                lines.append(f"Summary: {line.strip()}")
                break
            if re.search(r"Tests:\s+\d+", line):
                lines.append(f"Summary: {line.strip()}")
                break

        lines.append("")
        lines.append(output[-1000:] if len(output) > 1000 else output)
        return "\n".join(lines)

    # Tests failed
    lines.append("❌ TESTS FAILED")
    lines.append("")

    # Extract summary
    for line in output.split("\n"):
        if re.search(r"\d+ failed", line, re.IGNORECASE):
            lines.append(f"Summary: {line.strip()}")
            break
        if re.search(r"Tests:\s+.+failed", line):
            lines.append(f"Summary: {line.strip()}")
            break

    lines.append("")

    # Parse failures
    if "pytest" in framework_name:
        failures = _parse_pytest_failures(output)
    elif framework_name in ("jest", "vitest"):
        failures = _parse_jest_failures(output)
    else:
        failures = []

    if failures:
        lines.append(f"FAILURES ({len(failures)}):")
        lines.append("-" * 40)
        for i, f in enumerate(failures, 1):
            lines.append(f"\n{i}. {f.get('test', 'unknown test')}")
            if f.get("file"):
                lines.append(f"   File: {f['file']}")
            if f.get("error"):
                lines.append(f"   Error: {f['error']}")
            if f.get("lines"):
                for loc in f["lines"][:2]:
                    lines.append(f"   At: {loc}")
    else:
        # Raw output fallback
        lines.append("Raw output (last 50 lines):")
        raw_lines = [l for l in output.split("\n") if l.strip()][-50:]
        lines.extend(raw_lines)

    lines.append("")
    lines.append("=" * 40)
    lines.append(
        "Use the failure details above to fix the failing tests. "
        "After fixing, call run_tests again to verify."
    )

    return "\n".join(lines)


def test_file(path: str) -> str:
    """
    Run tests in a specific file only.
    Faster than running the full suite when fixing one file.
    """
    return run_tests(path=path)
