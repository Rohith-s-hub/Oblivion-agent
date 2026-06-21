# FastAPI Knowledge Pack

## CRITICAL: Pydantic v2 is the Default and Breaking Changes Are Everywhere

FastAPI 0.100+ uses Pydantic v2 by default. Pydantic v1 and v2 are NOT compatible.
NEVER mix v1 and v2 syntax in the same project.

Key v2 changes that silently break v1 code:

    # v1 - DEAD, do not use
    class User(BaseModel):
        class Config:
            orm_mode = True
        @validator("email")
        def email_must_be_lower(cls, v):
            return v.lower()

    # v2 - CORRECT
    class User(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        @field_validator("email")
        @classmethod
        def email_must_be_lower(cls, v: str) -> str:
            return v.lower()

ALWAYS pin FastAPI and Pydantic together:
    fastapi==0.115.0
    pydantic==2.9.2
    pydantic-settings==2.5.2


## Project Setup

### Directory Structure
    my_api/
      app/
        __init__.py
        main.py
        config.py
        dependencies.py
        models/   (SQLAlchemy ORM)
        schemas/  (Pydantic)
        routers/
        services/
        db/
          session.py
          base.py
      tests/conftest.py
      pyproject.toml
      .env

### Bootstrap
    python -m venv .venv
    source .venv/bin/activate
    pip install fastapi uvicorn[standard] pydantic-settings sqlalchemy asyncpg
    pip install alembic python-jose[cryptography] passlib[bcrypt] python-multipart
    pip install pytest pytest-asyncio httpx

### app/config.py - Settings with Pydantic-Settings
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from functools import lru_cache

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)
        app_name: str = "My API"
        debug: bool = False
        secret_key: str
        database_url: str
        allowed_origins: list[str] = ["http://localhost:3000"]

    @lru_cache
    def get_settings() -> Settings:
        return Settings()

ALWAYS use @lru_cache on the settings factory. Without it, .env is re-read on every request.

### app/db/session.py - Async SQLAlchemy
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.config import get_settings

    settings = get_settings()
    DATABASE_URL = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(
        DATABASE_URL,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    AsyncSessionLocal = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,  # CRITICAL for async
    )

expire_on_commit=False is CRITICAL. Without it, accessing attributes after await
session.commit() triggers lazy-load attempts that fail with MissingGreenlet errors.

### app/dependencies.py
    from typing import Annotated, AsyncGenerator
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.session import AsyncSessionLocal

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    DbDep = Annotated[AsyncSession, Depends(get_db)]


## CRITICAL: Common Foot-Guns

### 1. Sync Functions in Async Endpoints Block the Event Loop
    # BAD - blocks entire server
    @app.get("/users")
    async def get_users():
        time.sleep(1)
        result = requests.get(url)
        return result

    # GOOD
    @app.get("/users")
    async def get_users():
        await asyncio.sleep(1)
        async with httpx.AsyncClient() as client:
            result = await client.get(url)
        return result

If you MUST call sync code, use run_in_threadpool:
    from fastapi.concurrency import run_in_threadpool
    result = await run_in_threadpool(blocking_function, arg)

### 2. Pydantic Models Are NOT SQLAlchemy Models
NEVER use the same class for both. Keep separate:
    # models/user.py - SQLAlchemy ORM
    class UserORM(Base):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True)
        email: Mapped[str] = mapped_column(unique=True)

    # schemas/user.py - Pydantic
    class UserResponse(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        id: int
        email: str

### 3. response_model Does NOT Validate Input
response_model only filters OUTPUT. It does NOT validate the incoming request body.
NEVER rely on it to sanitize sensitive fields -- explicitly exclude in the schema.

### 4. BackgroundTasks Are NOT Reliable
BackgroundTasks run in the same process after response. If server crashes, task lost.
For critical work (emails, payments, notifications): use Celery or ARQ.
BackgroundTasks are only for fire-and-forget low-stakes ops like audit logging.

### 5. Startup/Shutdown MUST Use lifespan
    # BAD - deprecated, will be removed
    @app.on_event("startup")
    async def startup(): ...

    # GOOD
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        yield
        # shutdown

    app = FastAPI(lifespan=lifespan)

### 6. Path Parameters With Slashes Break Routing
    # BAD - GET /files/docs/report.pdf hits 404
    @app.get("/files/{file_path}")

    # GOOD - use :path converter
    @app.get("/files/{file_path:path}")

### 7. Optional[X] in Pydantic v2 is NOT the Same as X | None = None
    # v2: field is REQUIRED, value can be None
    name: Optional[str]

    # If you want optional with default None:
    name: str | None = None

ALWAYS be explicit about defaults in Pydantic v2 schemas.


## File Templates

### Router with Full CRUD
    from typing import Annotated
    from fastapi import APIRouter, HTTPException, status, Query
    from sqlalchemy import select
    from app.dependencies import DbDep, CurrentUser
    from app.models.post import PostORM
    from app.schemas.post import PostCreate, PostUpdate, PostResponse

    router = APIRouter()

    @router.get("/", response_model=list[PostResponse])
    async def list_posts(db: DbDep, skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
        result = await db.execute(
            select(PostORM).where(PostORM.is_deleted == False).offset(skip).limit(limit)
        )
        return result.scalars().all()

    @router.post("/", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
    async def create_post(payload: PostCreate, db: DbDep, current_user: CurrentUser):
        post = PostORM(**payload.model_dump(), author_id=current_user.id)
        db.add(post)
        await db.flush()
        await db.refresh(post)
        return post

    @router.patch("/{post_id}", response_model=PostResponse)
    async def update_post(post_id: int, payload: PostUpdate, db: DbDep, current_user: CurrentUser):
        post = await db.get(PostORM, post_id)
        if not post:
            raise HTTPException(404, "Not found")
        if post.author_id != current_user.id:
            raise HTTPException(403, "Forbidden")
        update_data = payload.model_dump(exclude_unset=True)  # CRITICAL
        for key, val in update_data.items():
            setattr(post, key, val)
        await db.flush()
        await db.refresh(post)
        return post

### Pydantic Schemas Pattern
    from pydantic import BaseModel, ConfigDict, field_validator
    from datetime import datetime

    class PostBase(BaseModel):
        title: str
        body: str | None = None

    class PostCreate(PostBase):
        @field_validator("title")
        @classmethod
        def title_not_empty(cls, v: str) -> str:
            if not v.strip():
                raise ValueError("Title cannot be blank")
            return v.strip()

    class PostUpdate(BaseModel):
        # NEVER inherit from PostBase for updates -- all fields must be optional
        title: str | None = None
        body: str | None = None

    class PostResponse(PostBase):
        model_config = ConfigDict(from_attributes=True)
        id: int
        author_id: int
        created_at: datetime

### Dependency Injection for Auth Roles
    def require_role(*roles: str):
        async def checker(user = Depends(get_current_user)):
            if user.role not in roles:
                raise HTTPException(403, f"Required roles: {roles}")
            return user
        return checker

    AdminUser = Annotated[UserORM, Depends(require_role("admin"))]

    @router.delete("/{id}")
    async def delete(id: int, admin: AdminUser, db: DbDep): ...

### Alembic Async Setup (env.py key parts)
    from sqlalchemy.ext.asyncio import async_engine_from_config
    from app.db.base import Base
    target_metadata = Base.metadata

    async def run_migrations_online():
        connectable = async_engine_from_config(
            config.get_section(config.config_ini_section),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()


## EDGE CASES AND GOTCHAS

### 1. model_dump(exclude_unset=True) is Critical for PATCH
Without it, optional fields with None defaults null out existing data:
    payload = PostUpdate(title="New")
    payload.model_dump()                  # {"title": "New", "body": None}
    payload.model_dump(exclude_unset=True) # {"title": "New"}
ALWAYS use exclude_unset=True in PATCH handlers.

### 2. SQLAlchemy Async Lazy Loading -> MissingGreenlet
    post = await db.get(PostORM, post_id)
    author_name = post.author.name  # CRASHES - lazy load

All relationship loading must be eager:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(PostORM).where(PostORM.id == post_id)
        .options(selectinload(PostORM.author))
    )

### 3. Sync Routes Run in Thread Pool Automatically
    @app.get("/sync")
    def sync_endpoint():  # no async -- safe for blocking
        return {"ok": True}
FastAPI runs non-async routes via anyio.to_thread.run_sync. But they cannot share
async resources. NEVER mix sync and async in the same dependency chain.

### 4. GET Requests Don't Support Request Bodies
FastAPI does not support Body() on GET endpoints. Use query parameters or POST.

### 5. response_model_exclude_none=True Silently Drops Fields
Drops ALL None fields, including ones that should be explicit null.

### 6. Middleware Execution Order is Reversed
Last middleware added wraps the OUTERMOST layer. CORS must be added LAST
so it runs FIRST on incoming requests.

### 7. HTTPException detail Accepts Any JSON-Serializable Value
    raise HTTPException(400, detail={"code": "INVALID", "fields": ["email"]})
Use structured dicts for machine-readable errors.

### 8. Alembic Autogenerate Misses Some Changes
Does NOT detect: stored procedures, sequences, some CHECK constraints, table drops
without include_schemas. ALWAYS review generated migration files manually.

### 9. pytest-asyncio Requires asyncio_mode = "auto"
Without it, async tests need @pytest.mark.asyncio. Forgetting the mark makes the
test pass silently without running.

### 10. Depends Called ONCE Per Request (Even if Used Multiple Places)
FastAPI caches dependency results per-request. Two endpoints depending on get_db
in the same chain share ONE session. Don't design dependencies assuming repeat calls.

### 11. Path Operations Detected as Sync When You Forget async
    @app.get("/data")
    def get_data():  # SYNC - runs in thread pool
        await something()  # SyntaxError
Forgetting async on routes that use await fails at parse time, but forgetting on
routes that should be async (using async libraries) silently degrades performance.

### 12. UUID Columns Need Proper SQLAlchemy Type
    # BAD - string-typed, slower index, no DB validation
    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid.uuid4()))

    # GOOD
    from sqlalchemy.dialects.postgresql import UUID
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


## BACKUP-BEFORE-CHANGE Protocol

### Before Any Alembic Migration
    pg_dump $DATABASE_URL > /tmp/db_$(date +%Y%m%d_%H%M%S).sql
    alembic current > /tmp/alembic_head_before.txt
    alembic revision --autogenerate -m "description"
    cat alembic/versions/<new_file>.py  # READ before upgrade
    alembic upgrade head
    alembic current  # verify

### Before Changing Pydantic Response Schemas
    git stash push -m "pre-schema-change"
    git checkout -b refactor/schema-<name>
    grep -r "SchemaName" app/ --include="*.py"
ALWAYS version your API (v1, v2) before changing response schemas.

### Before Upgrading FastAPI or Pydantic
    pip freeze > /tmp/requirements_before.txt
    pytest --tb=short > /tmp/tests_before.txt
    pip install fastapi --upgrade pydantic --upgrade
    pytest --tb=short > /tmp/tests_after.txt
    diff /tmp/tests_before.txt /tmp/tests_after.txt

### Before Adding New Middleware
    curl -I http://localhost:8000/health > /tmp/headers_before.txt
    # After adding:
    curl -I http://localhost:8000/health > /tmp/headers_after.txt
    diff /tmp/headers_before.txt /tmp/headers_after.txt


## DIAGNOSTIC RECIPES

### When 422 Unprocessable Entity Returned Unexpectedly
    1. Check full response body for detail array:
       {"detail": [{"loc": ["body", "field"], "msg": "...", "type": "..."}]}
    2. Common causes:
       - Required field missing or null
       - Type mismatch (string vs int)
       - Pydantic v2 validator raised ValueError
    3. Print exact payload: print(response.json())
    4. If from query param, check Query() annotation matches client type

### When MissingGreenlet Raised
    1. Find traceback line with "greenlet_spawn"
    2. Add selectinload() or joinedload() for that relationship:
       select(PostORM).options(selectinload(PostORM.author))
    3. If from response_model conversion: ORM object accessed after session closed.
       Use expire_on_commit=False AND load relationships before returning.
    4. NEVER return an ORM object after the session context has exited.

### When Dependency Injection Behaves Unexpectedly
    1. Add print in dependency to confirm it's called
    2. Check app.dependency_overrides isn't leftover from previous test run
    3. Confirm Annotated alias matches the dependency function
    4. For class-based deps, confirm __call__ is async if route is async

### When Alembic upgrade head Fails Mid-Migration
    1. Check alembic_version table:
       psql $DATABASE_URL -c "SELECT * FROM alembic_version;"
    2. Restore from backup if data at risk:
       psql $DATABASE_URL < /tmp/db_TIMESTAMP.sql
    3. Fix the migration operation
    4. If partial-applied + cannot restore:
       - Manually undo successful DB changes
       - psql $DATABASE_URL -c "UPDATE alembic_version SET version_num='previous';"
       - Re-run: alembic upgrade head

### When CORS Errors in Browser But Not curl
    1. CORSMiddleware must be added AFTER other middleware (last = runs first)
    2. Origin exact match: "http://localhost:3000" != "http://localhost:3000/"
    3. allow_credentials=True needed if client sends cookies/Authorization
    4. Test preflight:
       curl -X OPTIONS http://localhost:8000/api/v1/users \
         -H "Origin: http://localhost:3000" \
         -H "Access-Control-Request-Method: POST" -v
    5. If using nginx, check it isn't stripping CORS headers

### When Tests Pass Locally But Fail in CI
    1. Check Python version mismatch
    2. Test database isn't cleaned between runs - use unique DBs or drop/create
    3. Import order issues - CI runs stricter resolution
    4. Hardcoded localhost URLs - use ASGITransport pattern instead
    5. Confirm asyncio_mode = "auto" is in pyproject.toml


## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| 422 Unprocessable Entity | Body or query fails Pydantic validation | Read detail array; fix client payload or schema |
| MissingGreenlet | Lazy-load in async context | selectinload() or joinedload() |
| RuntimeError no running event loop | Async called from sync at import time | Move into lifespan handler |
| AttributeError __fields__ | Pydantic v1 API on v2 model | Use .model_dump(), model_fields |
| IntegrityError duplicate key | Unique constraint violated | try/except IntegrityError; return 409 |
| 404 on valid route | Trailing slash mismatch | redirect_slashes=False or match exactly |
| dependency_overrides not working in tests | Override set after app created | Set BEFORE creating test client |
| Task was destroyed pending | Background task not awaited | Use lifespan to await pending tasks |
| Cannot import from pydantic | v1 import path with v2 installed | Update: from pydantic import field_validator |
| CORS header missing on errors | Exception before CORSMiddleware processes | Add CORS in exception handlers explicitly |


## Anti-Patterns

### NEVER Use Global Mutable State for Request Resources
    # BAD - module-level session shared across requests
    db = AsyncSessionLocal()
Async sessions aren't coroutine-safe when shared. Use Depends(get_db).

### NEVER Catch All Exceptions and Return 200
    try:
        return await fetch_data()
    except Exception:
        return {"data": None}  # hides all errors
Monitoring depends on correct status codes. Let exceptions propagate.

### NEVER Store Secrets in Pydantic Model Defaults
    secret_key: str = "hardcoded-change-me"
Ships secret in source control. Use .env and validate non-empty at startup.

### NEVER Use datetime.utcnow() - Deprecated in Python 3.12
    # BAD
    now = datetime.utcnow()  # naive, deprecated
    # GOOD
    now = datetime.now(timezone.utc)

### NEVER Serialize ORM Objects Without from_attributes
    class UserResponse(BaseModel):
        model_config = ConfigDict(from_attributes=True)
        id: int
        email: str

### NEVER Block the Event Loop in Middleware
    @app.middleware("http")
    async def log(request, call_next):
        response = await call_next(request)
        with open("log.txt", "a") as f:  # BAD - sync file IO blocks loop
            f.write(...)
        return response
Use aiofiles or async-safe logging.

### NEVER Use response_model to Sanitize Sensitive Fields by Accident
Explicitly exclude password_hash, tokens, etc. from the response schema class.
Don't rely on field omission as a security boundary.


## Production Checklist

- Pydantic v2 syntax throughout (ConfigDict, field_validator, model_dump)
- All settings via pydantic-settings from env vars
- No hardcoded secrets or DATABASE_URL in source
- docs_url and redoc_url set to None in production
- lifespan handler used (not deprecated on_event)
- expire_on_commit=False on AsyncSession maker
- All relationships use selectinload/joinedload in async
- PATCH endpoints use model_dump(exclude_unset=True)
- Update schemas have all fields Optional with None defaults
- Global exception handlers for RequestValidationError and IntegrityError
- CORSMiddleware with explicit allowed_origins (no wildcard in prod)
- File uploads validate content_type and size BEFORE writing disk
- Server-generated UUID filenames for uploads (never client filename)
- BackgroundTasks replaced with Celery/ARQ for critical work
- Alembic uses async_engine_from_config
- All migrations reviewed manually before production
- alembic upgrade head in deploy pipeline before app starts
- Tests use httpx.AsyncClient with ASGITransport
- asyncio_mode = "auto" in pyproject.toml
- dependency_overrides cleared after each test
- datetime.now(timezone.utc) everywhere (no utcnow)
- UUID columns use SQLAlchemy UUID type, not String
- pool_pre_ping=True on async engine
- Rate limiting on auth and public endpoints (slowapi or nginx)
- Request body size limited (uvicorn --limit-concurrency + nginx client_max_body_size)
