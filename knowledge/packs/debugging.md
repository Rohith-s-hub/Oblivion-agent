# Debugging Knowledge Pack - Common Failures and Fixes

## CRITICAL: "localhost refused to connect" / ERR_CONNECTION_REFUSED

This is the #1 issue. Causes in order of likelihood:

1. Server is bound to 127.0.0.1 only, not 0.0.0.0
   - React/Vite: set server.host: true in vite.config.js
   - Vue/Vite: same fix
   - Next.js: use next dev -H 0.0.0.0
   - Express: app.listen(3000, '0.0.0.0')

2. Wrong port - server is on different port
   - Check what start_server actually reported
   - Vite default: 5173 (NOT 3000)
   - Next.js default: 3000
   - Always pass explicit port= to start_server

3. Server crashed silently
   - Check the server log file path returned by start_server
   - Use read_file on the log to see the error
   - Common: missing dependency -> npm install

4. Server not actually started
   - start_server returned but process died
   - Check with list_servers
   - Look at log file for crash trace

5. Firewall blocking
   - Rare on dev machines, common on cloud VMs

## DIAGNOSTIC RECIPE: When user says "localhost refused to connect"

    Step 1: list_servers -> see what's running
    Step 2: read_file(/tmp/oblivion-server-XXXXX.log) -> see actual error
    Step 3: Diagnose based on log content
    Step 4: stop_server old one, start_server with fix
    Step 5: Wait 5-10 seconds before claiming success

## Common Build Tool Errors

| Error | Meaning | Fix |
|---|---|---|
| npm ERR! ENOENT package.json | Wrong directory | cd into project root first |
| npm ERR! peer dep missing | Version conflict | npm install --legacy-peer-deps |
| EADDRINUSE :::3000 | Port already taken | Kill old process or use different port |
| Module not found | Missing install or typo | npm install pkg or check path |
| Cannot find module 'X' (Node) | Not installed | npm install X |
| ENOSPC: no space left | Disk full | Free up space |
| Killed (no other message) | OOM (out of memory) | Increase swap, close other apps |

## Python Server Errors

| Error | Fix |
|---|---|
| ModuleNotFoundError | pip install module or check venv activated |
| Port already in use | lsof -i :8000 then kill the process |
| IndentationError | Mixed tabs/spaces - use 4 spaces |
| ImportError: attempted relative import | Run as python -m package.module |

## Database Errors

| Error | Fix |
|---|---|
| OperationalError: no such table | Run migrations: python manage.py migrate or flask db upgrade |
| connection refused (postgres) | Postgres not running: sudo service postgresql start |
| SQLite database is locked | Another process has it open; close other connections |

## Browser/Frontend Issues

| Symptom | Likely Cause | Fix |
|---|---|---|
| Blank white page | JS error in console | Open DevTools (F12), check Console tab |
| 404 on /static/X | Build not run / wrong path | npm run build, check public/ structure |
| CORS error | Backend not allowing frontend origin | Add CORS headers/middleware on backend |
| 401 Unauthorized | Auth token missing/expired | Check localStorage/cookies, login again |
| Mixed content (https/http) | Loading http resources on https page | Use https everywhere |

## Server Health Check Recipe

When you start a server and need to verify it works:

    1. start_server(command="npm run dev", port=3000, wait_seconds=8)
    2. run_bash(command="curl -s -o /dev/null -w '%{http_code}' http://localhost:3000")
       expect "200" or similar
    3. If non-200: read_file on the log path that start_server returned
    4. Diagnose, fix, retry

## When Stuck - Escalation Order

1. Read the actual error log (don't guess)
2. Search the codebase for the error message
3. Check if dependencies are installed
4. Check if config files are correct
5. Check if ports are conflicted
6. Try with maximum verbosity: npm run dev -- --debug
