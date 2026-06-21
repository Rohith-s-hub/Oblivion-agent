# Testing Knowledge Pack

## CRITICAL: Test Isolation is Non-Negotiable

EVERY test MUST be runnable in isolation and in any order. NEVER rely on test execution
order. NEVER share mutable state between tests. ALWAYS use fixtures, factories, or
setup/teardown to create fresh test data. Tests that pass when run together but fail
individually are BROKEN tests - fix them immediately.

Use pytest -x --random-order or pytest --random-order-bucket=global to catch order
dependencies early. For vitest/jest use --no-cache --runInBand to verify isolation.

NEVER commit tests that only pass on your machine. Tests must pass in CI, on teammates'
machines, and in isolated containers.


## Project Setup

### Python (pytest)

    pip install pytest pytest-cov pytest-asyncio pytest-mock pytest-xdist pytest-randomly

pytest.ini at project root:

    [pytest]
    testpaths = tests
    python_files = test_*.py
    python_classes = Test*
    python_functions = test_*
    addopts =
        -ra
        --strict-markers
        --strict-config
        --cov=src
        --cov-report=term-missing
        --cov-branch
    asyncio_mode = auto
    markers =
        slow: marks tests as slow
        integration: marks tests as integration tests
        unit: marks tests as unit tests

Run tests:
    pytest                              # all
    pytest -x                           # stop on first failure
    pytest -k "test_user"               # filter by name
    pytest tests/test_api.py::test_login  # specific test
    pytest -m "not slow"                # skip marked
    pytest -n auto                      # parallel
    pytest --random-order               # randomized order

### JavaScript (vitest)

    npm install -D vitest @vitest/ui @vitest/coverage-v8

vitest.config.ts:

    import { defineConfig } from 'vitest/config'

    export default defineConfig({
      test: {
        globals: true,
        environment: 'node',
        coverage: {
          provider: 'v8',
          reporter: ['text', 'html', 'lcov'],
        },
        setupFiles: ['./tests/setup.ts'],
        isolate: true,
      }
    })

package.json scripts:
    "test": "vitest run",
    "test:watch": "vitest",
    "test:coverage": "vitest run --coverage"


## CRITICAL: Common Foot-Guns

### 1. Shared Mutable State
NEVER use module-level mutable variables:
    # WRONG
    cache = {}
    def test_one(): cache['key'] = 'value'
    def test_two(): assert 'key' not in cache  # FAILS if test_one ran first

    # CORRECT
    @pytest.fixture
    def cache(): return {}

### 2. Datetime and Randomness Make Tests Flaky
NEVER use datetime.now() or random() directly:
    # WRONG
    expires = datetime.now() + timedelta(days=1)  # flaky at midnight

    # CORRECT with freezegun
    from freezegun import freeze_time
    @freeze_time("2024-01-15 12:00:00")
    def test_expiry(): ...

    # vitest
    vi.setSystemTime(new Date('2024-01-15 12:00:00'))

For random: @pytest.fixture(autouse=True) that calls random.seed(42)

### 3. Database State Leakage
NEVER commit DB changes without cleanup:
    @pytest.fixture
    def db_session():
        connection = engine.connect()
        transaction = connection.begin()
        session = Session(bind=connection)
        yield session
        session.close()
        transaction.rollback()      # CRITICAL
        connection.close()

### 4. Async Test Pitfalls
NEVER call async without await:
    # WRONG - returns coroutine, never runs
    def test_async():
        result = async_function()  # FAILS

    # CORRECT
    @pytest.mark.asyncio
    async def test_async():
        result = await async_function()

    # vitest async is native
    test('async', async () => { await asyncFn() })

### 5. Mock Patching Scope
ALWAYS patch where used, NOT where defined:
    # WRONG - mymodule does "from datetime import datetime"
    @patch('datetime.datetime')  # doesn't affect mymodule

    # CORRECT
    @patch('mymodule.datetime')

### 6. External Service Dependencies
NEVER make real HTTP requests in unit tests:
    # WRONG
    response = requests.get("https://api.example.com/user/123")

    # CORRECT - pytest
    def test_fetch_user(requests_mock):
        requests_mock.get("https://api.example.com/user/123", json={"id": 123})

    # CORRECT - vitest
    global.fetch = vi.fn(() => Promise.resolve({
      json: () => Promise.resolve({ id: 123 })
    }))


## File Templates

### pytest conftest.py (comprehensive)

    import pytest
    import tempfile
    from pathlib import Path
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import StaticPool
    from myapp.database import Base
    from myapp.config import Settings

    @pytest.fixture(scope="session")
    def test_settings():
        return Settings(
            DATABASE_URL="sqlite:///:memory:",
            TESTING=True,
            SECRET_KEY="test-secret-key-never-use-in-production"
        )

    @pytest.fixture(scope="session")
    def engine(test_settings):
        engine = create_engine(
            test_settings.DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # CRITICAL: enable FK constraints in SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        Base.metadata.create_all(engine)
        yield engine
        Base.metadata.drop_all(engine)
        engine.dispose()

    @pytest.fixture
    def db_session(engine):
        connection = engine.connect()
        transaction = connection.begin()
        session = Session(bind=connection)
        yield session
        session.close()
        transaction.rollback()
        connection.close()

    @pytest.fixture
    def temp_dir():
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def mock_env(monkeypatch):
        def _set(**kwargs):
            for k, v in kwargs.items():
                monkeypatch.setenv(k, str(v))
        return _set

### vitest setup.ts

    import { afterEach, vi } from 'vitest'
    import { cleanup } from '@testing-library/react'

    afterEach(() => {
      vi.clearAllMocks()
      vi.restoreAllMocks()
      cleanup()
    })

    process.env.NODE_ENV = 'test'
    process.env.API_URL = 'http://localhost:3000'

    // Mock window.matchMedia for components
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation(query => ({
        matches: false,
        media: query,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })

### pytest test template

    import pytest
    from myapp.services import UserService

    class TestUserService:
        @pytest.fixture
        def user_service(self, db_session):
            return UserService(db_session)

        @pytest.fixture
        def sample_user(self, db_session):
            from myapp.models import User
            user = User(email="test@example.com")
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            return user

        def test_create_user(self, user_service):
            user = user_service.create(email="new@example.com")
            assert user.id is not None

        def test_get_nonexistent_user(self, user_service):
            with pytest.raises(UserService.NotFound):
                user_service.get_by_email("missing@example.com")

        @pytest.mark.parametrize("email,valid", [
            ("test@example.com", True),
            ("invalid", False),
            ("", False),
        ])
        def test_email_validation(self, user_service, email, valid):
            if valid:
                user = user_service.create(email=email)
                assert user.email == email
            else:
                with pytest.raises(ValueError):
                    user_service.create(email=email)


## Patterns

### Factory Pattern for Test Data

    @dataclass
    class UserFactory:
        email: str = field(default_factory=lambda:
            f"user{random.randint(1000,9999)}@example.com")
        name: str = "Test User"
        is_active: bool = True

        def create(self, db_session, **overrides):
            data = {'email': self.email, 'name': self.name, 'is_active': self.is_active}
            data.update(overrides)
            user = User(**data)
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
            return user

    # in tests
    def test_thing(db_session, user_factory):
        user = user_factory.create(db_session, email="specific@example.com")
        admin = user_factory.create(db_session, is_active=True)

### Fixture Scoping Strategy

    # Session - expensive setup, shared across all tests
    @pytest.fixture(scope="session")
    def docker_services():
        subprocess.run(["docker-compose", "up", "-d"])
        yield
        subprocess.run(["docker-compose", "down"])

    # Module - shared within one file
    @pytest.fixture(scope="module")
    def large_dataset():
        return load_csv("test_data.csv")

    # Function (default) - fresh per test
    @pytest.fixture
    def db_session(engine): ...

### Parametrize for Combinatorial Testing
    @pytest.mark.parametrize("a,b,expected", [
        (2, 3, 5),
        (-2, -3, -5),
        (0, 0, 0),
    ], ids=["positive", "negative", "zero"])
    def test_add(a, b, expected):
        assert add(a, b) == expected

    # vitest
    it.each([
      [2, 3, 5],
      [-2, -3, -5],
    ])('add(%i, %i) = %i', (a, b, expected) => {
      expect(add(a, b)).toBe(expected)
    })

### Mocking via Dependency Injection
    # WRONG - hard to test
    class UserService:
        def send_email(self, user_id):
            user = requests.get(f"https://api/users/{user_id}").json()
            smtp.send(user['email'], "Welcome")

    # CORRECT - injectable
    class UserService:
        def __init__(self, api_client, email_sender):
            self.api = api_client
            self.email = email_sender

    # test becomes simple
    def test_send_email():
        mock_api = Mock()
        mock_api.get_user.return_value = {'email': 'test@example.com'}
        mock_email = Mock()
        service = UserService(mock_api, mock_email)
        service.send_email(123)
        mock_email.send.assert_called_once_with('test@example.com', 'Welcome')

### Testing Async Code
    @pytest.mark.asyncio
    async def test_async_fetch(httpx_mock):
        httpx_mock.add_response(json={"status": "ok"})
        result = await fetch_data("https://api.example.com/data")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_concurrent():
        results = await asyncio.gather(op1(), op2(), op3())
        assert len(results) == 3

### Testing Error Conditions
    def test_divide_by_zero():
        with pytest.raises(ZeroDivisionError):
            divide(10, 0)

    def test_message_match():
        with pytest.raises(ValueError, match="must be positive"):
            process_age(-5)

    # vitest
    it('throws on invalid', () => {
      expect(() => processAge(-5)).toThrow('must be positive')
    })

### Snapshot Testing
NEVER snapshot dynamic data (timestamps, IDs). Validate structure instead:
    # WRONG - breaks on any timestamp change
    snapshot.assert_match(response_with_timestamps)

    # CORRECT - validate structure
    assert response.keys() == {'id', 'name', 'created_at'}
    assert isinstance(response['created_at'], str)
    assert datetime.fromisoformat(response['created_at'])


## EDGE CASES AND GOTCHAS

### 1. Pytest Fixture Order Depends on Scope, Not Definition
autouse=True with session scope runs BEFORE function scope, regardless of file order.

### 2. Pytest Caches Bytecode
After moving test files or changing fixture scopes: pytest --cache-clear

### 3. Vitest Globals Leak Between Files in Watch Mode
With globals: true, use isolate: true OR import explicitly:
    import { describe, it, expect } from 'vitest'

### 4. Mock Patch Persistence
    # NEVER do this (forgot to stop)
    mock_api = patch('myapp.api_client')
    mock_api.start()
    # affects ALL subsequent tests

ALWAYS use context manager or @patch decorator (auto-cleans).

### 5. SQLite Foreign Keys OFF by Default
Tests may pass with SQLite but fail on PostgreSQL.
ALWAYS enable in test engine via @event.listens_for(engine, "connect")

### 6. Temporary File Cleanup on Windows
tempfile.TemporaryDirectory() can fail if files still open.
Use shutil.rmtree(tmpdir, ignore_errors=True) for cross-platform safety.

### 7. Pytest capsys Doesn't Capture Subprocess
    capsys.readouterr().out  # subprocess output NOT here
    # Use subprocess.run(..., capture_output=True, text=True) and check result.stdout

### 8. Mocking datetime.now Requires Patching ALL References
    # module_a does: from datetime import datetime
    # module_b does: import datetime
    @patch('module_a.datetime')           # for module_a
    @patch('module_b.datetime.datetime')  # for module_b

### 9. Vitest vi.mock is Hoisted
vi.mock() runs BEFORE imports:
    # WRONG
    import { config } from './config'
    vi.mock('./api', () => ({ apiUrl: config.apiUrl }))  // ReferenceError

    # CORRECT
    vi.mock('./api', () => ({ apiUrl: 'http://mocked' }))

### 10. Pytest Marks Must Be Registered in Strict Mode
    # pytest.ini
    addopts = --strict-markers
    markers =
        slow: marks slow tests
    # @pytest.mark.slwo  # ERROR: unknown marker

### 11. Race Conditions in Async Tests are Silent
    # WRONG
    await asyncio.gather(write('key', 'v1'), write('key', 'v2'))
    assert cache.get('key') == 'v1'  # flaky

    # CORRECT
    assert cache.get('key') in ['v1', 'v2']

### 12. Coverage Misses Subprocess Code
Tests that spawn subprocess don't trigger coverage there.
Set COVERAGE_PROCESS_START env var and use coverage.process_startup() at module top.


## BACKUP-BEFORE-CHANGE Protocol

### Before refactoring fixtures used widely
    git checkout -b backup-before-fixture-refactor
    git add tests/conftest.py
    git commit -m "backup: conftest before refactor"
    git checkout main

    # Snapshot current passing tests
    pytest --co -q > /tmp/test_inventory_before.txt
    pytest --tb=no -q > /tmp/test_results_before.txt

### Before upgrading test framework versions
    cp pytest.ini pytest.ini.backup
    cp package.json package.json.backup
    pytest -v > /tmp/pytest_output_before_upgrade.txt 2>&1

### Before database schema changes affecting fixtures
    cp tests/test.db tests/test.db.backup
    alembic current > /tmp/alembic_state_before.txt

### Before mock refactoring across many tests
    git add tests/
    git commit -m "snapshot: tests before mock refactor"
    pytest -v --tb=short > /tmp/test_output_baseline.txt 2>&1


## DIAGNOSTIC RECIPES

### When tests pass locally but fail in CI
    1. Match Python/Node version exactly to CI
       pyenv local 3.11.7  # match CI
       pip install -r requirements-lock.txt
    2. Run multiple times to catch flaky:
       for i in {1..10}; do pytest -x || break; done
    3. Run with random order:
       pytest --random-order-bucket=global
    4. Run parallel like CI:
       pytest -n auto
    5. Check CI logs for: missing env vars, file permissions,
       network timeouts, database connection failures
    6. Reproduce in same Docker image:
       docker run -it python:3.11.7-slim bash

### When fixtures are not being found
    1. Verify conftest.py location (pytest searches UP from test file)
       find . -name "conftest.py"
    2. Show all fixtures and where defined:
       pytest --fixtures -v
    3. Check for name collisions:
       grep -r "@pytest.fixture" tests/ | grep "def fixture_name"
    4. Verify imports in conftest.py:
       python -c "import tests.conftest"

### When mocks are not working
    1. Verify patch target:
       import mymodule
       print(mymodule.function_to_mock.__module__)
       # Patch at USE site: @patch('mymodule.function_to_mock')
    2. Verify mock is being called:
       print(mock_obj.call_count)
       print(mock_obj.call_args_list)
       mock_obj.assert_called()
    3. Ensure mock active before code runs:
       with patch('mymodule.api') as mock_api:
           mock_api.get.return_value = {'data': 'test'}
           result = mymodule.fetch_data()
    4. For instance creation, mock the CLASS:
       @patch('mymodule.MyClass')
       def test_x(MockClass):
           MockClass.return_value.method.return_value = 'test'

### When database tests are failing
    1. Verify transaction rollback:
       print(f"In transaction: {db_session.in_transaction()}")
       db_session.rollback()
       leaked = db_session.query(Model).all()
       print(f"Leaked rows: {len(leaked)}")
    2. Check autoflush issues:
       with db_session.no_autoflush: ...
    3. Verify constraints enabled (SQLite):
       result = db_session.execute("PRAGMA foreign_keys")
       print(result.fetchone())
    4. Check migration state:
       alembic current

### When async tests hang or timeout
    1. Add timeout to find culprit:
       @pytest.mark.timeout(5)
       async def test_x(): ...
    2. Check for missing await:
       result = async_function()
       print(type(result))  # if <class 'coroutine'>: missing await
    3. Clean event loop:
       @pytest.fixture
       def event_loop():
           loop = asyncio.new_event_loop()
           yield loop
           for task in asyncio.all_tasks(loop):
               task.cancel()
           loop.close()
    4. Check for blocking calls in async:
       # time.sleep() in async function = BLOCK
       # use await asyncio.sleep() instead

### When coverage reports inaccurate
    1. Check source path:
       pytest --cov=src --cov-report=term-missing
    2. Verify tests actually run:
       pytest --collect-only
       pytest -v | grep SKIPPED
    3. For multiprocessing:
       # .coveragerc
       [run]
       concurrency = multiprocessing
       parallel = True
       # then: coverage combine && coverage report


## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| fixture 'xyz' not found | Fixture in wrong conftest.py | Move to parent conftest.py or import explicitly |
| ScopeMismatch fixture uses lower scope fixture | Higher scope depends on lower scope | Make dependency same/higher scope |
| RuntimeError Event loop is closed | pytest-asyncio not configured | asyncio_mode = auto in pytest.ini |
| AssertionError Mock called with ... | Mock not called or wrong args | Print mock.call_args_list to debug |
| sqlite3.IntegrityError FOREIGN KEY | FKs disabled in SQLite | Add PRAGMA foreign_keys=ON via event listener |
| ModuleNotFoundError in tests | sys.path issue | pythonpath = . in pytest.ini; run from project root |
| Tests pass alone fail together | Shared state or order dependency | pytest --random-order to find; fix teardown |
| asyncio.TimeoutError | Operation never completes | @pytest.mark.timeout(5); check for missing await |
| UnmappedInstanceError SQLAlchemy | Instance outside session | Keep instances within active session |
| vi.mock not working | Mock after import using it | Move vi.mock() to top of file (auto-hoisted) |
| Mock object is not iterable | Mock where iterable expected | mock.__iter__.return_value = iter([...]) |
| Database is locked SQLite | Concurrent access without StaticPool | poolclass=StaticPool in create_engine |
| AttributeError __enter__ on mock | Mock not configured as context manager | mock.__enter__.return_value = ... |


## Anti-Patterns

### NEVER test implementation details
    # WRONG - asserts on private state
    assert service._internal_cache == {...}

    # CORRECT - test public behavior
    user = service.create_user("test@example.com")
    assert user.email == "test@example.com"

Tests on internals break on refactor even when behavior unchanged.

### NEVER use time.sleep() for timing
    # WRONG
    trigger_job()
    time.sleep(5)  # hope it's done
    assert job_complete()

    # CORRECT - poll with timeout
    def wait_for(condition, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            if condition(): return True
            time.sleep(0.1)
        raise TimeoutError()

### NEVER catch broad Exception in test error cases
    # WRONG - hides bugs
    try: process(None)
    except Exception: pass

    # CORRECT
    with pytest.raises(ValueError, match="cannot be None"):
        process(None)

### NEVER leak resources
ALWAYS yield + close in fixtures. Open connections cause "too many open files".

### NEVER over-mock (testing mocks, not code)
    # WRONG - mocks everything internal
    def test(mock_db, mock_validator, mock_cache, mock_logger):
        # testing that mocks call mocks

    # CORRECT - mock only external boundaries
    def test(db_session, mock_external_api):
        user = UserFactory.create(db_session)
        mock_external_api.fetch.return_value = {"status": "verified"}
        result = process_user(user.id)
        assert result.verified is True

### NEVER use print for test debugging
    # WRONG - lost in test output
    print(f"Result: {result}")

    # CORRECT - use caplog
    def test_x(caplog):
        with caplog.at_level(logging.DEBUG):
            ...
        assert "Result: 30" in caplog.text

### NEVER mix slow and fast tests without markers
    @pytest.mark.slow
    @pytest.mark.integration
    def test_slow_integration(): ...
    # Run fast: pytest -m "not slow"

### NEVER create god fixtures
    # WRONG - every test gets everything
    @pytest.fixture
    def everything():
        return {'db': ..., 'user': ..., 'api': ..., 'cache': ...}

    # CORRECT - separate concerns
    @pytest.fixture
    def db_session(): ...
    @pytest.fixture
    def sample_user(db_session): ...


## Production Checklist

- All tests pass with: pytest -x --random-order
- Coverage above threshold: pytest --cov --cov-fail-under=80
- No skipped tests without documented reason
- No @pytest.mark.skip in main branch
- Integration tests pass against production-like environment
- Average suite execution time under 10 minutes
- Individual test files under 30 seconds
- No tests with time.sleep() exceeding 1 second
- All slow tests marked @pytest.mark.slow
- Database fixtures properly tear down (no leaked connections)
- Tests run on every pull request
- Tests run on all supported Python/Node versions
- Coverage reports uploaded to coverage service
- Failing tests block merge
- Flaky tests quarantined or fixed (not ignored)
- No hardcoded credentials in test files
- Test data factories available for all core models
- Fixture scope appropriate (not everything session-scoped)
- Test database migrations verified
- No reliance on external services without mocks
- Test execution time tracked over time
- Flaky test rate below 1%
- Coverage trend not decreasing
- Mock external API calls (no real requests in tests)
- Test artifacts not committed (coverage reports, test databases)
- conftest.py has docstrings for all fixtures
- Test markers documented in pytest.ini or vitest.config
- README explains how to run different test suites
