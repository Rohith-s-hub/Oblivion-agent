# Database Knowledge Pack

## CRITICAL: The Decisions You Cannot Undo Without Downtime

### Primary Key Type
ALWAYS use one of these two. Decide BEFORE the first table is created:

    -- Option A: BIGSERIAL (auto-increment, simple, sequential, fast inserts)
    id BIGSERIAL PRIMARY KEY

    -- Option B: UUID v4 (non-enumerable, safe in URLs, distributed-friendly)
    id UUID PRIMARY KEY DEFAULT gen_random_uuid()

NEVER use plain INTEGER (overflows at ~2.1B rows).
NEVER use UUID v1 (leaks MAC address, sortable by time).
NEVER mix UUID and BIGSERIAL across tables in the same schema.

PostgreSQL 14+: gen_random_uuid() built-in.
PostgreSQL 13-: CREATE EXTENSION pgcrypto; first.

### Character Encoding
ALWAYS create databases with UTF-8:

    CREATE DATABASE mydb
      ENCODING 'UTF8'
      LC_COLLATE 'en_US.UTF-8'
      LC_CTYPE 'en_US.UTF-8'
      TEMPLATE template0;

Changing encoding after creation = dump + drop + recreate + restore.

### Timezone Handling
ALWAYS use TIMESTAMPTZ. NEVER TIMESTAMP (without time zone).

    -- CORRECT
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- WRONG (silent data corruption when server timezone changes)
    created_at TIMESTAMP NOT NULL DEFAULT NOW()

Set app timezone explicitly: SET timezone = 'UTC';


## Project Setup

### PostgreSQL Initial Setup
    psql -U postgres
    CREATE USER myapp WITH PASSWORD 'strongpassword';
    CREATE DATABASE myappdb OWNER myapp ENCODING 'UTF8' TEMPLATE template0;
    GRANT ALL PRIVILEGES ON DATABASE myappdb TO myapp;
    \q

### Essential PostgreSQL Extensions
    CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid()
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";     -- trigram similarity search
    CREATE EXTENSION IF NOT EXISTS "unaccent";    -- accent-insensitive search
    CREATE EXTENSION IF NOT EXISTS "btree_gin";   -- GIN on scalar types

### SQLite Setup (CRITICAL pragmas at every connection)
    PRAGMA journal_mode=WAL;     -- concurrent reads
    PRAGMA foreign_keys=ON;      -- OFF by default!
    PRAGMA busy_timeout=5000;    -- avoid "database is locked"

SQLite foreign keys are NOT enforced by default. Silent data integrity hole.

### Connection String Formats
    # PostgreSQL sync (psycopg2)
    postgresql://user:pass@host:5432/dbname

    # PostgreSQL async (asyncpg)
    postgresql+asyncpg://user:pass@host:5432/dbname

    # PostgreSQL with SSL
    postgresql://user:pass@host:5432/dbname?sslmode=require

    # SQLite async (aiosqlite)
    sqlite+aiosqlite:///./local.db

    # SQLite in-memory (tests)
    sqlite+aiosqlite:///:memory:


## CRITICAL: Common Foot-Guns

### 1. N+1 Query Problem (Most Common Performance Killer)
    # BAD - 1 query + N follow-ups
    posts = session.execute(select(Post)).scalars().all()
    for post in posts:
        print(post.author.name)

    # GOOD - eager load
    posts = session.execute(
        select(Post).options(selectinload(Post.author))
    ).scalars().all()

ALWAYS check query count in tests. One bad relationship access = 10,000 queries/page.

### 2. Missing Index on Foreign Keys
PostgreSQL does NOT auto-create indexes on FK columns.

    -- Full table scan without index:
    SELECT * FROM comments WHERE post_id = $1;

    -- ALWAYS add:
    CREATE INDEX idx_comments_post_id ON comments(post_id);

SQLAlchemy: post_id = Column(ForeignKey("posts.id"), index=True)
Django: ForeignKey(..., db_index=True) -- default True

### 3. COUNT(*) vs COUNT(column)
    SELECT COUNT(*) FROM posts;        -- counts all rows (CORRECT for totals)
    SELECT COUNT(deleted_at) FROM posts; -- counts only NON-NULL deleted_at

NOT interchangeable. COUNT(column) silently gives wrong totals.

### 4. BETWEEN is Inclusive on Both Ends
    -- WRONG: misses last day except midnight
    WHERE created_at BETWEEN '2024-01-01' AND '2024-01-31'

    -- CORRECT: use explicit >= and <
    WHERE created_at >= '2024-01-01' AND created_at < '2024-02-01'

### 5. NULL Comparisons Always Return NULL
    WHERE deleted_at = NULL    -- WRONG: returns 0 rows always
    WHERE deleted_at IS NULL   -- CORRECT
    WHERE deleted_at != NULL   -- WRONG: returns 0 rows always
    WHERE deleted_at IS NOT NULL -- CORRECT

Most common silent SQL bug.

### 6. NOT IN With NULLs Returns Empty Set
    -- WRONG: if any author_id is NULL, returns 0 rows
    SELECT * FROM users WHERE id NOT IN (SELECT author_id FROM posts);

    -- CORRECT
    SELECT * FROM users u
    WHERE NOT EXISTS (SELECT 1 FROM posts p WHERE p.author_id = u.id);

### 7. Transaction Isolation Defaults to READ COMMITTED
For financial/inventory operations needing consistency:
    BEGIN;
    SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
    -- operations
    COMMIT;

### 8. TRUNCATE Does NOT Fire Triggers or Cascades
ON DELETE triggers don't fire. FK ON DELETE CASCADE doesn't propagate.
Use TRUNCATE only for bulk cleanup where you've verified no triggers matter.


## File Templates

### Standard PostgreSQL Table
    CREATE TABLE users (
        id          BIGSERIAL PRIMARY KEY,
        email       TEXT NOT NULL,
        name        TEXT NOT NULL DEFAULT '',
        role        TEXT NOT NULL DEFAULT 'user'
                        CHECK (role IN ('user', 'admin', 'moderator')),
        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
        metadata    JSONB NOT NULL DEFAULT '{}',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at  TIMESTAMPTZ,
        CONSTRAINT users_email_unique UNIQUE (email)
    );

    CREATE INDEX idx_users_active ON users(id) WHERE deleted_at IS NULL;
    CREATE INDEX idx_users_email ON users(email);

    -- Auto-update updated_at trigger
    CREATE OR REPLACE FUNCTION update_updated_at()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER users_updated_at
        BEFORE UPDATE ON users
        FOR EACH ROW EXECUTE FUNCTION update_updated_at();

### Raw SQL Query Patterns
    -- Upsert (INSERT or UPDATE on conflict)
    INSERT INTO users (email, name) VALUES ($1, $2)
    ON CONFLICT (email)
    DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
    RETURNING *;

    -- Soft delete
    UPDATE users SET deleted_at = NOW()
    WHERE id = $1 AND deleted_at IS NULL
    RETURNING id;

    -- Keyset pagination (FAST for large tables)
    SELECT * FROM posts
    WHERE created_at < $1  -- cursor: last seen created_at
    ORDER BY created_at DESC
    LIMIT 20;

    -- Bulk insert with conflict skip
    INSERT INTO tags (name, slug) VALUES ($1, $2), ($3, $4), ($5, $6)
    ON CONFLICT (slug) DO NOTHING;

### SQLAlchemy Model Template
    from datetime import datetime
    from sqlalchemy import BigInteger, Boolean, Text, TIMESTAMP, Index, CheckConstraint
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from sqlalchemy.sql import func

    class Base(DeclarativeBase): pass

    class TimestampMixin:
        created_at: Mapped[datetime] = mapped_column(
            TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
        )
        updated_at: Mapped[datetime] = mapped_column(
            TIMESTAMP(timezone=True), server_default=func.now(),
            onupdate=func.now(), nullable=False
        )

    class User(TimestampMixin, Base):
        __tablename__ = "users"
        __table_args__ = (
            Index("idx_users_email", "email"),
            CheckConstraint("role IN ('user', 'admin')", name="valid_role"),
        )
        id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
        role: Mapped[str] = mapped_column(Text, default="user", nullable=False)
        deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))


## Patterns

### Indexing Strategy
    -- Index columns in WHERE, JOIN ON, ORDER BY
    -- Do NOT index low-cardinality (boolean, status with 3 values) alone

    -- Composite index: most selective column first
    CREATE INDEX idx_posts_author_status ON posts(author_id, status);
    -- Supports: WHERE author_id = X [AND status = Y]
    -- Does NOT support: WHERE status = Y alone (no left-prefix match)

    -- Partial index (smaller, faster for common filters)
    CREATE INDEX idx_posts_active ON posts(created_at DESC)
    WHERE deleted_at IS NULL;

    -- GIN for full-text search
    CREATE INDEX idx_posts_fts ON posts USING GIN(
        to_tsvector('english', title || ' ' || body)
    );

    -- GIN for JSONB containment
    CREATE INDEX idx_users_metadata ON users USING GIN(metadata);

    -- Check unused indexes (drop them, they slow writes)
    SELECT schemaname, tablename, indexname, idx_scan
    FROM pg_stat_user_indexes ORDER BY idx_scan ASC;

### Full-Text Search (PostgreSQL)
    -- Store tsvector as generated column (faster than computing at query time)
    ALTER TABLE posts ADD COLUMN search_vector TSVECTOR
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(title, '') || ' ' || coalesce(body, ''))
        ) STORED;

    CREATE INDEX idx_posts_search ON posts USING GIN(search_vector);

    SELECT *, ts_rank(search_vector, query) AS rank
    FROM posts, to_tsquery('english', 'django & performance') query
    WHERE search_vector @@ query
    ORDER BY rank DESC LIMIT 20;

### Connection Pooling
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,          -- persistent connections
        max_overflow=20,       -- extra under burst load
        pool_timeout=30,       -- seconds waiting for connection
        pool_recycle=1800,     -- recycle every 30min (prevents stale)
        pool_pre_ping=True,    -- test before using
    )

PgBouncer for production: transaction pooling preferred.
NEVER use session pooling with Django CONN_MAX_AGE > 0 simultaneously.

### Soft Delete Pattern
    -- Schema
    ALTER TABLE posts ADD COLUMN deleted_at TIMESTAMPTZ;

    -- Partial index for active rows
    CREATE INDEX idx_posts_active ON posts(id) WHERE deleted_at IS NULL;

    -- All queries filter
    SELECT * FROM posts WHERE deleted_at IS NULL AND id = $1;

### Transactions and Locking
    -- Optimistic locking (no DB lock)
    UPDATE posts SET title = $1, version = version + 1
    WHERE id = $2 AND version = $3;
    -- If 0 rows updated: conflict, retry

    -- Pessimistic locking (holds lock)
    BEGIN;
    SELECT * FROM wallets WHERE user_id = $1 FOR UPDATE;
    UPDATE wallets SET balance = balance - $2 WHERE user_id = $1;
    COMMIT;

    -- SKIP LOCKED (job queue pattern)
    BEGIN;
    SELECT * FROM jobs WHERE status = 'pending'
    ORDER BY created_at LIMIT 1
    FOR UPDATE SKIP LOCKED;
    UPDATE jobs SET status = 'processing' WHERE id = $1;
    COMMIT;

    -- Advisory locks (app-level mutex)
    SELECT pg_try_advisory_lock(123);   -- returns true if acquired
    SELECT pg_advisory_unlock(123);

### Migration Safety
SAFE (no lock, no downtime):
    -- ADD COLUMN with DEFAULT (PostgreSQL 11+)
    -- CREATE INDEX CONCURRENTLY
    -- ADD CONSTRAINT ... NOT VALID

UNSAFE (table lock):
    -- ADD COLUMN NOT NULL without DEFAULT (rewrites table in PG < 11)
    -- DROP COLUMN (marks invisible, doesn't reclaim space)
    -- ALTER COLUMN TYPE (rewrites table)
    -- ADD CONSTRAINT (validates all rows, holds lock)


## EDGE CASES AND GOTCHAS

### 1. VARCHAR(255) and TEXT Have IDENTICAL Performance in PostgreSQL
NO performance difference. VARCHAR(n) just adds a length constraint check.
ALWAYS use TEXT in PostgreSQL unless you need a specific length constraint.

### 2. OFFSET Pagination is O(N) -- Slower as OFFSET Grows
    -- OFFSET 1,000,000 takes seconds, not milliseconds
    SELECT * FROM posts ORDER BY created_at DESC LIMIT 20 OFFSET 1000000;

Use keyset pagination beyond first few pages:
    -- Next page (cursor from previous page)
    SELECT * FROM posts
    WHERE (created_at, id) < ($last_ts, $last_id)
    ORDER BY created_at DESC, id DESC LIMIT 20;

### 3. SELECT * is a Time Bomb
Schema changes silently change response shape. Sensitive new columns get exposed.
Removed columns cause KeyError. ALWAYS name columns explicitly.

### 4. JSONB vs JSON
JSONB: binary-parsed, indexable, supports containment (@>, ?). Use this.
JSON: raw text, faster writes, preserves key order/duplicates.
ALWAYS use JSONB unless preserving key order matters.

### 5. Deadlocks Caused by Lock ORDER, Not Duration
    -- Transaction A: locks row 1 then row 2
    -- Transaction B: locks row 2 then row 1 -> DEADLOCK

ALWAYS acquire locks in consistent order.
For multi-row updates: ORDER BY id before processing.
Handle DeadlockError and retry.

### 6. Index on Expression vs Column
    -- NOT used for this query:
    CREATE INDEX idx_users_email ON users(email);
    SELECT * FROM users WHERE LOWER(email) = 'x@y.com';

    -- Need expression index:
    CREATE INDEX idx_users_email_lower ON users(LOWER(email));

### 7. Autovacuum Falls Behind Under Heavy Writes
Dead tuples accumulate -> table bloat -> slow queries (even SELECT).

Monitor:
    SELECT n_dead_tup, n_live_tup FROM pg_stat_user_tables WHERE relname = 'posts';

If n_dead_tup >> n_live_tup: VACUUM ANALYZE posts;

### 8. Sequences Skip Values on Rollback
    INSERT...  -- id=1
    BEGIN; INSERT...  -- id=2
    ROLLBACK;
    INSERT...  -- id=3 (NOT 2)

Gaps in auto-increment are NORMAL. NEVER rely on sequential or gapless IDs.

### 9. Foreign Key Checks Lock Referenced Row
INSERT on child takes ROW SHARE lock on parent. Under high concurrency with FK inserts
and parent mutations, causes surprising lock contention. Use DEFERRABLE INITIALLY DEFERRED
for bulk operations inserting children before parents.

### 10. ON DELETE CASCADE Silently Deletes at Scale
Delete user -> ALL their posts, comments, likes, sessions cascade-deleted. No audit.
NEVER use CASCADE on important user data without:
- Audit log table via trigger
- Soft-delete as primary mechanism
- Separate hard-delete job with explicit confirmation

### 11. SQLite is Single-Writer
Only one writer at a time. WAL mode allows concurrent reads but not concurrent writes.
For web servers with multiple workers: use PostgreSQL. SQLite is for dev or embedded.

### 12. LIKE With Leading Wildcard Cannot Use B-tree Index
    -- Full table scan:
    WHERE title LIKE '%django%'
    -- Can use index:
    WHERE title LIKE 'django%'

For contains/prefix searches:
    CREATE INDEX idx_posts_title_trgm ON posts USING GIN(title gin_trgm_ops);
    SELECT * FROM posts WHERE title % 'django';  -- trigram similarity


## BACKUP-BEFORE-CHANGE Protocol

### Before Any Schema Migration
    # Full dump
    pg_dump -Fc $DATABASE_URL > /tmp/backup_$(date +%Y%m%d_%H%M%S).dump
    # Restore: pg_restore -d $DATABASE_URL /tmp/backup_TIMESTAMP.dump

    # Table-only dump (faster for single table changes)
    pg_dump -Fc -t tablename $DATABASE_URL > /tmp/table_backup.dump

    # Check current state (Alembic / Django)
    alembic current
    python manage.py showmigrations | grep "\[X\]" | tail -5

### Before Adding Index to Large Table
    -- Check table size
    SELECT pg_size_pretty(pg_total_relation_size('posts'));

    -- For tables > 1GB: ALWAYS use CONCURRENTLY
    CREATE INDEX CONCURRENTLY idx_posts_author_id ON posts(author_id);

NEVER run CREATE INDEX (non-concurrent) on a live production table > 100MB.

### Before Destructive Operation (DROP, TRUNCATE, large DELETE)
    -- Export affected rows
    COPY (SELECT * FROM posts WHERE status = 'spam')
    TO '/tmp/spam_backup.csv' CSV HEADER;

    -- Or backup to table
    CREATE TABLE posts_deleted_backup AS
    SELECT * FROM posts WHERE status = 'spam';

    -- THEN delete
    DELETE FROM posts WHERE status = 'spam';

### Before Changing Column Type or Constraint
    -- Check current distribution
    SELECT status, COUNT(*) FROM posts GROUP BY status;

    -- Check for values that will fail new constraint
    SELECT COUNT(*) FROM posts WHERE length(title) > 100;


## DIAGNOSTIC RECIPES

### When Queries Are Suddenly Slow
    1. Check for missing indexes:
       EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM posts WHERE author_id = 123;
       -- "Seq Scan" on large table = no index

    2. Check stats freshness:
       SELECT last_analyze, last_autoanalyze
       FROM pg_stat_user_tables WHERE relname = 'posts';
       -- If null/old: ANALYZE posts;

    3. Check bloat:
       SELECT n_dead_tup, n_live_tup,
              n_dead_tup::float / NULLIF(n_live_tup, 0) AS bloat_ratio
       FROM pg_stat_user_tables WHERE relname = 'posts';
       -- If > 0.2: VACUUM ANALYZE posts;

    4. Check lock contention:
       SELECT pid, query, wait_event_type, wait_event, state
       FROM pg_stat_activity WHERE wait_event_type = 'Lock';

    5. Long-running queries:
       SELECT pid, now() - query_start AS duration, query
       FROM pg_stat_activity WHERE state != 'idle'
       ORDER BY duration DESC;

    6. Kill blocking query:
       SELECT pg_cancel_backend(pid);     -- graceful
       SELECT pg_terminate_backend(pid);  -- force

### When Migration Fails Mid-Run
    1. Check what succeeded:
       SELECT * FROM alembic_version;  -- or django_migrations

    2. If atomic and DB consistent: restore from backup, fix, re-run
       pg_restore -d $DATABASE_URL /tmp/backup_TIMESTAMP.dump

    3. If partial DDL applied: manually reverse, re-run migration

    4. Stuck with lock:
       SELECT pid, query FROM pg_stat_activity WHERE state = 'active';
       SELECT pg_terminate_backend(pid);

### When Connection Pool Exhausted
    1. Check connections:
       SELECT count(*), state FROM pg_stat_activity GROUP BY state;
       SHOW max_connections;

    2. Find connection-holders:
       SELECT pid, usename, application_name, state, query_start
       FROM pg_stat_activity WHERE state != 'idle'
       ORDER BY query_start;

    3. Verify pool_size + max_overflow < max_connections (default 100)

    4. Immediate fix: kill idle-in-transaction
       SELECT pg_terminate_backend(pid)
       FROM pg_stat_activity
       WHERE state = 'idle in transaction'
         AND query_start < NOW() - INTERVAL '5 minutes';

### When Data Unexpectedly Missing
    1. Check soft-delete:
       SELECT * FROM posts WHERE id = $1;  -- including deleted

    2. Check audit log if exists

    3. Check cascade deletes:
       SELECT conname, confdeltype FROM pg_constraint
       WHERE confrelid = 'posts'::regclass;
       -- confdeltype 'c' = CASCADE

    4. Restore specific rows from backup:
       pg_restore -t posts /tmp/backup.dump | psql $DATABASE_URL


## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| column already exists | Migration run twice | Use IF NOT EXISTS, check version tables |
| deadlock detected | Locking rows in opposite order | ORDER BY id; catch and retry |
| value too long for varchar(N) | VARCHAR limit exceeded | Change to TEXT or increase limit |
| duplicate key violates unique | INSERT on existing | ON CONFLICT DO UPDATE or DO NOTHING |
| serialize access due to concurrent update | SERIALIZABLE conflict | Catch SerializationFailure, retry |
| relation does not exist | Table not created, wrong schema | Check CREATE; set search_path |
| can't adapt type | Python object has no type mapping | Register adapter or convert before insert |
| too many connections | Pool exhausted | Reduce pool_size, add PgBouncer |
| remaining slots reserved | At max_connections | Terminate idle; PgBouncer |
| cursor already closed | Session used after close in async | Stay within session context manager |
| database is locked (SQLite) | Concurrent writes, no WAL | PRAGMA journal_mode=WAL; or use PostgreSQL |
| operator does not exist text = integer | Type mismatch | Cast: WHERE id = $1::bigint |


## Anti-Patterns

### NEVER Store Comma-Separated Values in a Column
    -- BAD: tags TEXT  -- "python,django,web"
Cannot index. Cannot filter efficiently. Cannot enforce integrity.
GOOD: normalized join table (post_tags with post_id + tag_id).

### NEVER Use SELECT * in Application Code
Schema changes silently break code. Sensitive new columns leak.
ALWAYS name columns: select(User.id, User.email)

### NEVER Run CREATE INDEX (non-CONCURRENTLY) on Live Production Tables
Holds ACCESS EXCLUSIVE lock. Blocks ALL reads/writes for the entire build.
10M rows = minutes of downtime.
ALWAYS use CREATE INDEX CONCURRENTLY in production.

### NEVER Use Application-Side Joins as Substitute for SQL JOINs
    # BAD - disguised N+1
    posts = fetch_all_posts()
    for p in posts:
        p["author"] = fetch_user_by_id(p["author_id"])

Network round-trip per row. Use SQL JOIN.

### NEVER Use time.sleep() as a Distributed Lock
Does not guarantee exclusivity. Multiple processes wake simultaneously.
Use pg_try_advisory_lock(), Redis SETNX, or a proper job queue.

### NEVER Store Passwords in Recoverable Format
NEVER plaintext, MD5, SHA1, or unsalted SHA256.
Use bcrypt or argon2: passlib.hash.bcrypt.hash(password)
MD5/SHA256 hex are reversible with rainbow tables.

### NEVER Ignore Database Warnings in Development
"implicit coercion", "transaction in progress" warnings are structural problems.
They become silent data corruption in production. Fix all warnings before shipping.

### NEVER Use NOW() in Migration Data Backfills
    -- BAD: all rows get identical timestamps
    UPDATE posts SET published_at = NOW() WHERE published_at IS NULL;

Breaks ordering, analytics, time-distribution logic.
Use existing meaningful column or leave NULL until real data exists.


## Production Checklist

- All datetime columns are TIMESTAMPTZ (never TIMESTAMP)
- Database created with UTF-8 encoding
- Primary key type (BIGSERIAL or UUID) chosen and consistent
- All foreign key columns have explicit indexes
- No VARCHAR(n) in PostgreSQL -- use TEXT with CHECK constraints
- JSONB instead of JSON
- Full-text search uses tsvector stored column with GIN index (not LIKE '%term%')
- All large-table indexes created with CREATE INDEX CONCURRENTLY
- Soft delete pattern (deleted_at column) for user-data tables
- Partial index on deleted_at IS NULL for active queries
- Connection pool sized: pool_size + max_overflow < max_connections
- pool_pre_ping=True to detect stale connections
- PgBouncer configured for production
- NEVER CONN_MAX_AGE > 0 + PgBouncer transaction mode together
- Autovacuum monitored (n_dead_tup tracked)
- EXPLAIN ANALYZE run on queries touching tables > 100k rows
- No N+1 patterns (verified with query logging in staging)
- No SELECT * in application queries
- No NOT IN with nullable subquery columns (use NOT EXISTS)
- Keyset pagination for any list endpoint where OFFSET > 500 expected
- Backups automated and restore tested monthly
- pg_stat_user_indexes checked for unused indexes
- All migrations reviewed manually before production
- DDL migrations during low-traffic unless using CONCURRENTLY
- SQLite WAL mode and foreign_keys PRAGMA at every connection open
- Transaction isolation set explicitly for financial/inventory ops
- All passwords hashed with bcrypt or argon2 (never MD5/SHA)
