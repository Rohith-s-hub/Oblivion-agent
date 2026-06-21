# Security Knowledge Pack

## CRITICAL: Security Is Not a Feature -- It Is a Constraint on Every Decision

Every line of code that touches user input, authentication, file I/O, external data,
or configuration is a security decision. NEVER treat security as a post-deployment
concern. NEVER ship "we'll harden it later." The agent writing code must apply these
rules at the point of generation, not after.

Security failures do not announce themselves. They accumulate silently and surface
as breaches, data leaks, or account takeovers. The threat model is: assume all user
input is malicious, all secrets will leak to logs, all dependencies have vulnerabilities,
and all defaults are wrong.

ALWAYS apply defense in depth: multiple independent layers, so that a single bypass
does not give an attacker full access.


## Project Setup

### Python Security Dependencies
    pip install cryptography passlib[bcrypt] python-jose[cryptography]
    pip install bleach html-sanitizer python-multipart
    pip install bandit safety pip-audit

### Node.js Security Dependencies
    npm install bcryptjs jsonwebtoken helmet express-rate-limit
    npm install express-validator dompurify isomorphic-dompurify
    npm install --save-dev npm-audit-resolver

### Security Scanning Commands (Run in CI)
    # Python: static analysis for security issues
    bandit -r app/ -ll

    # Python: check dependencies for known CVEs
    pip-audit

    # Node.js: check dependencies for known CVEs
    npm audit --audit-level=high

    # Secrets scanning (detect committed secrets)
    pip install detect-secrets
    detect-secrets scan > .secrets.baseline
    detect-secrets audit .secrets.baseline

    # Run before every commit:
    git diff --cached | detect-secrets-hook --baseline .secrets.baseline


## CRITICAL: Common Foot-Guns

### 1. SQL Injection -- Raw String Interpolation in Queries
    # BAD -- SQL injection
    query = f"SELECT * FROM users WHERE email = '{email}'"
    cursor.execute(query)

    # BAD -- still injectable via format
    query = "SELECT * FROM users WHERE email = '%s'" % email
    cursor.execute(query)

    # GOOD -- parameterized (driver handles escaping)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))

    # GOOD -- ORM (parameterized under the hood)
    User.objects.filter(email=email)
    session.execute(select(User).where(User.email == email))

NEVER construct SQL with string concatenation or f-strings. NEVER.
The parameter placeholder varies by driver: %s (psycopg2), ? (sqlite3), :name (SQLAlchemy text()).

    # SQLAlchemy text() with named params -- CORRECT
    from sqlalchemy import text
    result = session.execute(
        text("SELECT * FROM users WHERE email = :email"),
        {"email": email}
    )

### 2. Command Injection -- Shell=True With User Input
    # BAD -- shell=True lets attacker run arbitrary commands
    import subprocess
    subprocess.run(f"convert {filename} output.png", shell=True)
    # attacker passes filename = "x; rm -rf /"

    # GOOD -- list form, no shell interpretation
    subprocess.run(["convert", filename, "output.png"])

    # GOOD -- validate filename before use
    import re
    if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
        raise ValueError("Invalid filename")
    subprocess.run(["convert", filename, "output.png"])

NEVER use shell=True with any input derived from user data, environment variables,
or external systems. NEVER use os.system() with dynamic input.

### 3. Path Traversal -- User-Controlled File Paths
    # BAD -- attacker passes "../../../etc/passwd"
    def read_file(filename):
        with open(f"/uploads/{filename}") as f:
            return f.read()

    # GOOD -- resolve and verify path stays inside allowed directory
    from pathlib import Path

    UPLOAD_DIR = Path("/uploads").resolve()

    def read_file(filename: str) -> str:
        safe_path = (UPLOAD_DIR / filename).resolve()
        if not str(safe_path).startswith(str(UPLOAD_DIR)):
            raise PermissionError("Path traversal detected")
        with open(safe_path) as f:
            return f.read()

ALWAYS resolve() before checking. A path like "/uploads/a/../../../etc/passwd" resolves
to "/etc/passwd". Without resolve(), startswith() checks fail to catch traversals.

### 4. Mass Assignment -- Binding Request Data Directly to Models
    # BAD -- attacker sends {"role": "admin", "is_active": true} in request body
    user = User(**request.json())
    db.session.add(user)

    # GOOD -- explicit allowlist of accepted fields
    allowed = {"name", "email", "bio"}
    data = {k: v for k, v in request.json().items() if k in allowed}
    user = User(**data)

In Django DRF, ALWAYS use read_only_fields on serializers for fields that must not
be set by the client. In FastAPI, ALWAYS use separate Create/Update schemas that only
expose the fields users are allowed to set.

### 5. Insecure Direct Object Reference (IDOR)
    # BAD -- user can access any order by changing the ID
    @app.get("/orders/{order_id}")
    async def get_order(order_id: int, db: DbDep):
        return await db.get(Order, order_id)

    # GOOD -- verify ownership
    @app.get("/orders/{order_id}")
    async def get_order(order_id: int, db: DbDep, user: CurrentUser):
        order = await db.get(Order, order_id)
        if not order or order.user_id != user.id:
            raise HTTPException(status_code=404)  # 404 not 403: don't confirm existence

NEVER return 403 when a resource exists but the user lacks access -- return 404.
Returning 403 leaks that the resource exists, enabling enumeration.

### 6. Secrets in Logs, Errors, and Stack Traces
    # BAD -- password or token appears in log output
    logger.debug(f"Authenticating user with password={password}")
    logger.info(f"Token: {jwt_token}")
    return JSONResponse({"error": str(exception)})  # may contain internal paths or data

    # GOOD
    logger.debug("Authenticating user", extra={"user_id": user_id})
    # NEVER log passwords, tokens, card numbers, SSNs, or raw exceptions to users

In production: ALWAYS use a generic error message for 500s. Log the full traceback
server-side to a log aggregator (not stdout in a publicly visible place).

### 7. Timing Attacks on String Comparison
    # BAD -- short-circuit comparison leaks timing information
    if token == expected_token:

    # GOOD -- constant-time comparison
    import hmac
    if hmac.compare_digest(token.encode(), expected_token.encode()):

ALWAYS use hmac.compare_digest() when comparing secrets, tokens, or hashes.
Regular == returns early on first mismatch, leaking how many characters matched.


## File Templates

### Password Hashing (Python)
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


    def hash_password(password: str) -> str:
        return pwd_context.hash(password)


    def verify_password(plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)

NEVER use hashlib.md5, hashlib.sha256, or hashlib.sha512 for passwords.
These are fast hashing algorithms -- designed for speed, terrible for passwords.
bcrypt, argon2, and scrypt are designed to be slow. Use passlib with bcrypt.
NEVER roll your own password hashing.

### JWT Tokens (Python)
    from datetime import datetime, timezone, timedelta
    from jose import JWTError, jwt
    from app.config import get_settings

    settings = get_settings()
    ALGORITHM = "HS256"


    def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
        expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=30))
        payload = {
            "sub": subject,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "access",
        }
        return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


    def create_refresh_token(subject: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(days=7)
        payload = {
            "sub": subject,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
            "type": "refresh",
        }
        return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


    def decode_token(token: str) -> dict:
        try:
            payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
            if payload.get("type") != "access":
                raise JWTError("Wrong token type")
            return payload
        except JWTError:
            raise ValueError("Invalid or expired token")

NEVER use algorithm="none" -- this disables signature verification entirely.
ALWAYS validate the "type" claim to prevent refresh tokens being used as access tokens.
ALWAYS validate "exp" -- python-jose does this automatically but verify it is not disabled.

### Security Headers Middleware (FastAPI)
    from fastapi import Request
    from fastapi.responses import Response
    from starlette.middleware.base import BaseHTTPMiddleware


    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "frame-ancestors 'none';"
            )
            if request.url.scheme == "https":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains; preload"
                )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

### Rate Limiting (FastAPI with slowapi)
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.post("/auth/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...):
        ...

    @app.post("/auth/register")
    @limiter.limit("3/hour")
    async def register(request: Request, ...):
        ...

### Input Sanitization (HTML)
    import bleach

    ALLOWED_TAGS = ["b", "i", "u", "em", "strong", "p", "br", "ul", "ol", "li"]
    ALLOWED_ATTRIBUTES = {}


    def sanitize_html(raw: str) -> str:
        return bleach.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True)

    # For rich text editors (more permissive):
    from html_sanitizer import Sanitizer
    sanitizer = Sanitizer()
    clean = sanitizer.sanitize(user_html)

NEVER render raw user HTML without sanitization. NEVER trust client-side sanitization.
Server-side sanitization is the only defense against stored XSS.

### Secret Management (.env Pattern)
    # .env (NEVER commit this file)
    SECRET_KEY=at-least-32-random-characters-generated-by-secrets-module
    DATABASE_URL=postgresql://user:pass@localhost:5432/db
    JWT_SECRET=another-long-random-string

    # Generate secrets properly:
    python -c "import secrets; print(secrets.token_hex(32))"

    # .gitignore (ALWAYS include these)
    .env
    .env.*
    !.env.example
    *.pem
    *.key
    secrets/

    # .env.example (COMMIT this -- shows required vars without values)
    SECRET_KEY=
    DATABASE_URL=
    JWT_SECRET=

### CSRF Protection (Django)
    # Django has CSRF middleware enabled by default -- do NOT disable it
    # For DRF with token auth, CSRF is not required (stateless)
    # For DRF with SessionAuthentication, CSRF IS required

    # Frontend: read CSRF token from cookie and send in header
    const csrfToken = document.cookie
        .split(';')
        .find(c => c.trim().startsWith('csrftoken='))
        ?.split('=')[1];

    fetch('/api/endpoint', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });

### File Upload Security
    import magic  # python-magic, reads actual file bytes not extension
    from pathlib import Path
    import uuid

    ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
    UPLOAD_DIR = Path("/app/uploads").resolve()


    async def secure_upload(file: UploadFile) -> str:
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise ValueError(f"File exceeds {MAX_FILE_SIZE // 1024 // 1024}MB limit")

        # Check MIME type from actual bytes, not client-reported Content-Type
        mime = magic.from_buffer(content, mime=True)
        if mime not in ALLOWED_MIME_TYPES:
            raise ValueError(f"File type {mime} not allowed")

        # Generate safe filename -- NEVER use client-provided filename
        ext = {"image/jpeg": ".jpg", "image/png": ".png",
               "image/webp": ".webp", "image/gif": ".gif"}[mime]
        filename = f"{uuid.uuid4()}{ext}"

        dest = UPLOAD_DIR / filename
        dest.write_bytes(content)
        return filename

NEVER trust file.content_type from the client -- it is trivially spoofed.
ALWAYS read actual bytes and check MIME type with python-magic.
NEVER store uploads in a publicly web-accessible path without access control checks.
NEVER execute uploaded files.


## Patterns

### Authentication Flow (Complete)
    # 1. Registration
    async def register(email: str, password: str, db: AsyncSession) -> User:
        email = email.lower().strip()

        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            # Return same response as success to prevent enumeration
            raise HTTPException(status_code=400, detail="Registration failed")

        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password too short")

        user = User(email=email, hashed_password=hash_password(password))
        db.add(user)
        await db.commit()
        return user

    # 2. Login
    async def login(email: str, password: str, db: AsyncSession) -> dict:
        user = await get_user_by_email(db, email.lower().strip())
        # ALWAYS verify even if user not found (prevents timing attack)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=401, detail="Account disabled")

        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))

        # Store refresh token hash in DB for revocation
        await store_refresh_token(db, user.id, hash_token(refresh_token))

        return {"access_token": access_token, "refresh_token": refresh_token}

### Permission Checking Pattern
ALWAYS check permissions at the data layer, not just the route layer:

    # BAD -- only checks at route level, bypassed if function called elsewhere
    @router.get("/admin/users")
    async def list_users(user: CurrentUser):
        if user.role != "admin":
            raise HTTPException(403)
        return await get_all_users(db)

    # GOOD -- permission enforced inside the service function
    async def get_all_users(db: AsyncSession, requesting_user: User) -> list[User]:
        if requesting_user.role != "admin":
            raise PermissionError("Admin access required")
        return (await db.execute(select(User))).scalars().all()

### Sensitive Data Redaction in Logs
    import logging
    import re

    SENSITIVE_PATTERNS = [
        (re.compile(r'password=[^&\s]+'), 'password=***'),
        (re.compile(r'token=[^&\s]+'), 'token=***'),
        (re.compile(r'"password"\s*:\s*"[^"]*"'), '"password": "***"'),
        (re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'), '****-****-****-****'),
    ]


    class RedactingFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            msg = str(record.getMessage())
            for pattern, replacement in SENSITIVE_PATTERNS:
                msg = pattern.sub(replacement, msg)
            record.msg = msg
            record.args = ()
            return True

    logging.getLogger().addFilter(RedactingFilter())

### Environment-Based Secret Validation at Startup
    import secrets
    import sys

    def validate_secrets():
        required = ["SECRET_KEY", "DATABASE_URL", "JWT_SECRET"]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            print(f"FATAL: Missing required secrets: {missing}")
            sys.exit(1)

        secret_key = os.environ["SECRET_KEY"]
        if len(secret_key) < 32:
            print("FATAL: SECRET_KEY must be at least 32 characters")
            sys.exit(1)

        known_bad = {"changeme", "secret", "password", "example", "test"}
        if any(bad in secret_key.lower() for bad in known_bad):
            print("FATAL: SECRET_KEY contains a known insecure value")
            sys.exit(1)

    validate_secrets()  # call at app startup before serving requests


## EDGE CASES AND GOTCHAS

### 1. JWT "None" Algorithm Attack
Some JWT libraries accept {"alg": "none"} in the token header, which disables
signature verification. An attacker crafts an unsigned token and the server accepts it.

ALWAYS explicitly specify allowed algorithms when decoding:

    # python-jose
    jwt.decode(token, secret, algorithms=["HS256"])  # whitelist only

    # PyJWT
    jwt.decode(token, secret, algorithms=["HS256"])

NEVER pass algorithms=None or omit the algorithms parameter.

### 2. Timing Attack on User Enumeration via Login
    # BAD -- different response times reveal whether email exists
    user = db.get_user(email)
    if not user:
        return {"error": "User not found"}   # fast response
    if not verify_password(password, user.hash):
        return {"error": "Wrong password"}   # slower (bcrypt ran)

    # GOOD -- always run bcrypt even for nonexistent users
    user = db.get_user(email)
    dummy_hash = "$2b$12$invalidhashforsecuritypurposesonly"
    verify_password(password, user.hashed_password if user else dummy_hash)
    if not user or not verified:
        raise HTTPException(401, "Invalid credentials")

### 3. SSRF -- Server-Side Request Forgery via User-Supplied URLs
    # BAD -- attacker passes url="http://169.254.169.254/latest/meta-data/"
    # (AWS metadata endpoint, gives IAM credentials)
    async def fetch_og_data(url: str):
        async with httpx.AsyncClient() as client:
            return await client.get(url)

    # GOOD -- validate URL scheme and block private IP ranges
    import ipaddress
    from urllib.parse import urlparse

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
    ]

    def is_safe_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            return not any(ip in net for net in BLOCKED_NETWORKS)
        except ValueError:
            pass  # hostname, not IP -- resolve and re-check
        return True

### 4. ReDoS -- Regular Expression Denial of Service
    # BAD -- catastrophic backtracking on crafted input
    import re
    pattern = re.compile(r'^(a+)+$')
    pattern.match("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaab")  # hangs for seconds/minutes

Use timeout-wrapped regex for user-controlled input:

    import signal

    def safe_match(pattern: re.Pattern, text: str, timeout: int = 1):
        def handler(signum, frame):
            raise TimeoutError("Regex timeout")
        signal.signal(signal.SIGALRM, handler)
        signal.alarm(timeout)
        try:
            return pattern.match(text)
        finally:
            signal.alarm(0)

Or use the re2 library (Google RE2) which has linear-time guarantees:

    import re2  # pip install google-re2

### 5. Insecure Deserialization -- Never Use pickle With Untrusted Data
    # BAD -- arbitrary code execution via crafted pickle payload
    import pickle
    obj = pickle.loads(user_supplied_bytes)

    # GOOD -- use JSON, Pydantic, or msgpack for serialization
    import json
    obj = json.loads(user_supplied_bytes)

NEVER use pickle, marshal, or shelve with data from any external source.
NEVER use yaml.load() -- use yaml.safe_load() which disallows Python objects.

### 6. Open Redirect -- Unvalidated Redirect Targets
    # BAD -- attacker uses ?next=https://evil.com/phishing
    next_url = request.args.get("next", "/")
    return redirect(next_url)

    # GOOD -- only allow relative URLs or known safe domains
    from urllib.parse import urlparse

    def safe_redirect(url: str, allowed_host: str) -> str:
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != allowed_host:
            return "/"
        return url

### 7. Cookie Security Flags
    # ALWAYS set these flags on session/auth cookies
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,    # JS cannot read cookie (prevents XSS token theft)
        secure=True,      # HTTPS only (never sent over HTTP)
        samesite="lax",   # CSRF protection (lax allows top-level GET, strict blocks all cross-site)
        max_age=3600,
        path="/",
    )

    # samesite="none" requires secure=True -- without it, the cookie is rejected

### 8. Dependency Confusion Attack
If your package registry falls back to the public PyPI/npm when a private package
is not found, attackers publish a malicious package with the same name at a higher
version number on the public registry. Your CI installs the attacker's package.

ALWAYS pin exact versions in production requirements:

    # BAD
    requests>=2.28.0

    # GOOD
    requests==2.31.0

ALWAYS use a private registry (Nexus, Artifactory, AWS CodeArtifact) with
upstream proxying disabled or allowlisted for production builds.

### 9. HTTP Parameter Pollution
    # Attacker sends: POST /transfer?amount=100&amount=0
    # Some frameworks take the first, some take the last, some take both as a list
    # If your code does: amount = request.args["amount"] -- behavior is undefined

    # ALWAYS use explicit parameter extraction:

    # Flask
    amount = request.args.get("amount", type=float)

    # FastAPI -- declare as typed parameter, framework handles it
    async def transfer(amount: float = Query(..., gt=0)):

### 10. Stored XSS via Markdown Rendering
    # BAD -- markdown can contain raw HTML including <script>
    import markdown
    html = markdown.markdown(user_content)  # renders <script>alert(1)</script>

    # GOOD -- sanitize AFTER rendering
    import bleach
    raw_html = markdown.markdown(user_content)
    safe_html = bleach.clean(raw_html, tags=ALLOWED_TAGS, strip=True)

### 11. GraphQL Introspection and Depth Attacks
If you serve a GraphQL API, introspection is enabled by default and reveals your
entire schema to attackers. Nested queries can cause exponential database load:

    query {
        users {
            friends { friends { friends { friends { id email } } } }
        }
    }

ALWAYS disable introspection in production. ALWAYS set max query depth (strawberry,
ariadne, and graphene all have depth limiting middleware).

### 12. Environment Variable Leakage via Error Pages
Debug mode in Django/Flask prints all environment variables in the error page.
ALWAYS set DEBUG=False in production. ALWAYS verify no debug middleware is active.

    # Test this explicitly:
    curl -X GET http://yourapp.com/nonexistent-path
    # Should return 404, NOT a stack trace with env vars


## BACKUP-BEFORE-CHANGE Protocol

### Before Changing Authentication Logic
    git checkout -b security/auth-change-$(date +%Y%m%d)
    # Document the current auth flow in a comment at the top of the PR
    # Run the full auth test suite before and after:
    pytest tests/test_auth.py -v > /tmp/auth_tests_before.txt

### Before Rotating Secrets
    # 1. Generate new secret
    python -c "import secrets; print(secrets.token_hex(32))"

    # 2. For JWT rotation: support BOTH old and new secrets for a transition window
    #    (all existing tokens signed with old key, new tokens use new key)
    #    Run with dual-key verification for the token lifetime (e.g., 30 min to 24 hr)

    # 3. Invalidate old sessions if needed:
    #    Increment a global token_version counter in DB
    #    Reject any token where payload["version"] < current_version

    # 4. Update secret in secret manager / environment BEFORE deploying new code

### Before Adding a New Dependency
    # Check the package before installing
    pip-audit --requirement <(echo "package-name==version")

    # For npm
    npm audit --package-lock-only

    # Check the package on PyPI/npm for:
    # - Maintainer history and number of maintainers (1 maintainer = supply chain risk)
    # - Last publish date (abandoned packages get hijacked)
    # - Stars, downloads (low = untested)
    # - Source repository existence


## DIAGNOSTIC RECIPES

### When You Suspect SQL Injection Vulnerability
    1. Search codebase for interpolated SQL:
       grep -rn "execute.*%" app/ --include="*.py"
       grep -rn "execute.*f\"" app/ --include="*.py"
       grep -rn "execute.*format" app/ --include="*.py"
       grep -rn "raw(" app/ --include="*.py"  # Django .raw()

    2. For each hit: verify it uses parameterized form (%s with tuple, not string format)

    3. Run bandit for automated detection:
       bandit -r app/ -t B608  # B608 = hardcoded SQL expressions

    4. Test manually: append ' OR '1'='1 to a string parameter and confirm the app
       returns an error (rejected) rather than data (injected)

### When Secrets Are Found in Git History
    1. Rotate the secret IMMEDIATELY -- assume it is compromised
    2. Audit access logs for the period since the secret was committed
    3. Remove from git history (does NOT uncompromise -- rotate first):
       git filter-repo --path-glob '*.env' --invert-paths
       -- or use BFG Repo Cleaner for speed on large repos
    4. Force push to all remotes
    5. Notify all collaborators to re-clone -- cached clones still have the secret
    6. If the secret was a cloud credential: revoke in IAM console immediately
       before doing anything else

### When Authentication Is Bypassed
    1. Check if middleware is applied to ALL routes including new ones:
       -- FastAPI: is auth dependency in the router, not just individual endpoints?
       -- Django: is the view decorated with @login_required or LoginRequiredMixin?

    2. Check for routes that explicitly set permission_classes = [AllowAny]
       grep -rn "AllowAny\|permission_classes = \[\]" app/ --include="*.py"

    3. Check for OPTIONS method bypass:
       curl -X OPTIONS http://yourapp.com/api/sensitive -v
       -- should not return 200 with data

    4. Check for HTTP method override headers:
       curl -X POST http://yourapp.com/api/data -H "X-HTTP-Method-Override: GET"

    5. Verify JWT decode always specifies algorithm list:
       grep -rn "jwt.decode\|jwt\.decode" app/ --include="*.py"
       -- confirm algorithms= parameter is present and not ["none"] or wildcard

### When Rate Limiting Is Not Working
    1. Check if the client is sending requests from different IPs (distributed attack)
       -- IP-based rate limiting is insufficient for distributed attackers
       -- Add account-level rate limiting (limit per user ID, not per IP)

    2. Check if X-Forwarded-For header is spoofed:
       -- If behind a load balancer, the real IP comes from X-Forwarded-For
       -- Attackers can spoof this header if you trust it blindly
       -- ONLY trust X-Forwarded-For from your own load balancer's IP range

    3. Verify rate limiter storage is shared across workers:
       -- In-memory rate limiter in a multi-worker setup: each worker has its own counter
       -- Use Redis-backed rate limiting for multi-process/multi-instance deployments

    4. Check if rate limiter is applied before or after authentication:
       -- Login endpoints MUST be rate limited before auth check (else attacker can
          enumerate users via timing difference between "user not found" and "wrong password")


## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| psycopg2.errors.SyntaxError near user input | SQL injection vulnerability | Replace string interpolation with parameterized query |
| JWT decode fails with "algorithm not supported" | algorithms= param missing or misconfigured | Explicitly pass algorithms=["HS256"] |
| 401 on all requests after secret rotation | Old tokens signed with old key, new key rejects them | Implement dual-key verification during rotation window |
| CORS blocks requests despite being configured | Middleware order wrong or origin has trailing slash | Move CORSMiddleware to last add_middleware call; match origin exactly |
| File upload succeeds but content is wrong type | Trusting client Content-Type header | Use python-magic to check actual bytes, not reported MIME |
| Redirect sends user to external site | Open redirect via unvalidated next param | Validate redirect target is relative or known host |
| Rate limiter counts per-worker instead of globally | In-memory store in multi-worker setup | Switch to Redis-backed limiter (slowapi + Redis, django-ratelimit + cache) |
| Secrets visible in CI logs | Secret passed as CLI argument or printed in error | Pass secrets via environment variables; add log redaction filter |
| pickle.loads raises unexpected error | Untrusted data fed to deserializer | Replace with json.loads + Pydantic schema |
| XSS payload executes in browser | User HTML rendered without sanitization | Run bleach.clean() after markdown rendering |


## Anti-Patterns

### NEVER Store Plaintext Passwords or Reversibly Encrypted Passwords
Store only bcrypt/argon2 hashes. If you can decrypt a "password", it is not a hash.
Reason: database breach exposes every user's password. bcrypt hashes take years to
crack individually and cannot be batch-reversed.

### NEVER Use MD5 or SHA1 for Anything Security-Sensitive
MD5 and SHA1 are cryptographically broken. MD5 collisions are computable in seconds.
SHA1 collisions have been demonstrated (SHAttered attack). Use SHA-256 or better for
checksums, HMAC-SHA256 for MACs, bcrypt/argon2 for passwords.

### NEVER Disable SSL Certificate Verification in Production
    # BAD
    requests.get(url, verify=False)
    httpx.get(url, verify=False)

    # WHY: disables MITM protection entirely. Any network observer can intercept traffic.
    # GOOD: fix the certificate instead of disabling verification

### NEVER Use eval() or exec() on User Input
    # BAD -- arbitrary code execution
    result = eval(user_expression)
    exec(user_code)

    # WHY: these run arbitrary Python with full interpreter access
    # GOOD: use ast.literal_eval() for safe Python literal parsing, or a proper parser

### NEVER Trust User-Controlled HTTP Headers as Security Controls
    # BAD -- attacker sets X-Admin: true header
    if request.headers.get("X-Admin") == "true":
        return admin_data()

    # WHY: any client can set any HTTP header
    # GOOD: verify role from authenticated session/token only

### NEVER Use random for Security-Sensitive Values
    # BAD -- predictable, not cryptographically random
    import random
    token = ''.join(random.choices(string.ascii_letters, k=32))

    # GOOD -- cryptographically secure
    import secrets
    token = secrets.token_urlsafe(32)

    # For numeric codes (OTP):
    code = str(secrets.randbelow(1000000)).zfill(6)

### NEVER Log Request Bodies in Production at DEBUG Level by Default
Request bodies contain passwords (login), payment data, PII. Even temporary debug
logging of request bodies violates GDPR/PCI and risks secret exposure in log files.
If you must log request bodies for debugging, redact sensitive fields explicitly and
ensure the logging level is not enabled in production configuration.

### NEVER Return Detailed Error Messages to Clients in Production
    # BAD -- reveals internal structure, table names, file paths
    return JSONResponse({"error": str(exception)}, status_code=500)

    # GOOD
    logger.exception("Unhandled error processing request")
    return JSONResponse({"error": "Internal server error"}, status_code=500)


## Production Checklist

- All SQL queries use parameterized form (no f-strings or % formatting in SQL)
- subprocess calls use list form (no shell=True with dynamic input)
- File path operations use Path.resolve() with startswith check for traversal
- All user-supplied HTML sanitized with bleach after rendering
- Passwords hashed with bcrypt via passlib (not MD5/SHA1/SHA256)
- JWT decode specifies explicit algorithms= list (never omitted, never ["none"])
- JWT token type claim validated (access vs refresh)
- Sensitive string comparisons use hmac.compare_digest()
- Secrets loaded from environment variables (not hardcoded, not in source)
- .env file in .gitignore; .env.example committed without values
- Startup validates presence and minimum strength of all required secrets
- File uploads: MIME checked with python-magic (not client Content-Type)
- File uploads: server-generated UUID filename (never client filename)
- Upload directory not web-accessible without access control
- Rate limiting applied to auth, registration, and OTP endpoints
- Rate limiter uses Redis backend in multi-worker/multi-instance deployments
- Security headers middleware applied (X-Frame-Options, CSP, HSTS, etc.)
- HSTS enabled with includeSubDomains and long max-age on HTTPS endpoints
- CORS configured with exact allowed origins (no wildcard in production)
- Session/auth cookies have httponly=True, secure=True, samesite="lax"
- DEBUG=False in production (no stack traces, no env var dump in error pages)
- Generic 500 error messages to clients; full details only in server logs
- Log redaction filter applied for passwords, tokens, card numbers
- No eval(), exec(), pickle.loads(), yaml.load() with untrusted data
- No random module used for security tokens (use secrets module)
- Redirect targets validated against allowlist (no open redirects)
- External URL fetching validates against private IP range blocklist (SSRF)
- All dependencies pinned to exact versions in production
- pip-audit / npm audit run in CI with high severity as build failure
- detect-secrets or equivalent scanning in pre-commit hook
- IDOR protection: ownership verified before returning any resource
- 404 returned (not 403) when resource exists but user lacks access
- GraphQL introspection disabled in production (if applicable)
- SSL certificate verification enabled on all outbound HTTP clients
- No X-Forwarded-For trusted unless coming from known load balancer IP
