# Django Knowledge Pack

## CRITICAL: Project Foundations That Cannot Be Retrofitted

ALWAYS use a custom User model BEFORE the first migration. Django's built-in User cannot
be swapped after migrations exist without wiping the database.

    # accounts/models.py
    from django.contrib.auth.models import AbstractUser

    class User(AbstractUser):
        pass

    # settings.py
    AUTH_USER_MODEL = "accounts.User"

NEVER reference django.contrib.auth.models.User directly. ALWAYS use settings.AUTH_USER_MODEL
in models and get_user_model() in code:

    from django.conf import settings
    from django.contrib.auth import get_user_model
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    User = get_user_model()

ALWAYS split settings into base/dev/prod from day one.
NEVER commit SECRET_KEY. Use django-environ or python-decouple loading from .env.

## CRITICAL: Common Foot-Guns

### Mutable defaults
    # BAD: default=[]  -- shared across instances
    # GOOD: default=list  -- callable, new each time

### on_delete consequences
- CASCADE: delete child with parent (most common, dangerous)
- SET_NULL: requires null=True
- PROTECT: blocks delete if children exist
- DO_NOTHING: NEVER use, creates orphans

### null=True vs blank=True
- null=True: allows NULL in DB
- blank=True: allows empty in form validation
- For CharField/TextField: NEVER null=True. Use blank=True, default="".

### N+1 queries
    # BAD: posts = Post.objects.all(); for p in posts: print(p.author.name)
    # GOOD: Post.objects.select_related("author").all()
    # For M2M and reverse FK: prefetch_related

### get_or_create is NOT atomic
Under load, two threads can both "get nothing" and both "create" -> IntegrityError.
Wrap in try/except, or use select_for_update inside transaction.atomic.

### FileField does NOT delete files on delete
Add post_delete signal to clean up storage.

### request.data vs request.POST
ALWAYS use request.data in DRF views. POST is empty for JSON bodies.

## File Templates

### Custom User
    from django.contrib.auth.models import AbstractUser
    from django.db import models

    class User(AbstractUser):
        email = models.EmailField(unique=True)
        USERNAME_FIELD = "email"
        REQUIRED_FIELDS = ["username"]

### TimeStampedModel (use as base for EVERY model)
    import uuid
    from django.db import models

    class TimeStampedModel(models.Model):
        id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
        created_at = models.DateTimeField(auto_now_add=True)
        updated_at = models.DateTimeField(auto_now=True)
        class Meta:
            abstract = True

### DRF ViewSet (production pattern)
    from rest_framework import viewsets, permissions
    from rest_framework.decorators import action
    from rest_framework.response import Response

    class PostViewSet(viewsets.ModelViewSet):
        serializer_class = PostSerializer
        permission_classes = [permissions.IsAuthenticated, IsAuthorOrReadOnly]
        filterset_fields = ["status"]
        search_fields = ["title"]
        ordering = ["-created_at"]

        def get_queryset(self):
            return (Post.objects
                .select_related("author")
                .prefetch_related("tags")
                .filter(is_deleted=False))

        def perform_create(self, serializer):
            serializer.save(author=self.request.user)

### Service Layer (keep views thin)
    # posts/services.py
    from django.db import transaction

    @transaction.atomic
    def publish_post(post, published_by):
        if post.status == "published":
            raise ValueError("Already published")
        post.status = "published"
        post.save(update_fields=["status", "updated_at"])
        transaction.on_commit(lambda: send_notification.delay(post.id))
        return post

NEVER send emails/Celery tasks/external API calls inside transaction.atomic without
on_commit. If transaction rolls back, side effect already fired.

## EDGE CASES AND GOTCHAS

### 1. auto_now cannot be overridden in save()
Django silently overwrites your value. Use default=timezone.now if you need control.

### 2. QuerySet.delete() does NOT fire signals or Model.delete()
post_delete signals don't fire. FileField cleanup doesn't run.
For signals: iterate and .delete() each instance.

### 3. timezone.now() vs datetime.now()
With USE_TZ=True, datetime.now() is naive. Use timezone.now() always.

### 4. STATIC/MEDIA not served by Django in production
Dev server serves them; gunicorn doesn't. Use whitenoise for static, nginx for media.

### 5. CharField choices NOT validated at DB level
User can save any string. Add CheckConstraint in Meta.constraints for DB validation.

### 6. request.user in serializers requires context
Manual instantiation: PostSerializer(data=data, context={"request": request})

### 7. CONN_MAX_AGE conflicts with PgBouncer transaction pooling
Causes "SSL connection has been closed" errors. Pick one strategy.

### 8. ManyToManyField.set() clears AND re-adds (expensive)
For deltas: post.tags.set(new_tags, clear=False)

### 9. prefetch_related invalidated by .filter() after the fact
Use Prefetch objects with custom queryset:
    Prefetch("comments", queryset=Comment.objects.filter(active=True))

### 10. update_fields skips full_clean()
Signal handlers that need full state must re-fetch the object.

### 11. bulk_create skips save() signals
If post_save signals must fire, use create() in a loop inside transaction.atomic.

## BACKUP-BEFORE-CHANGE Protocol

### Before any migration operation
    pg_dump $DATABASE_URL > /tmp/db_backup_$(date +%Y%m%d_%H%M%S).sql
    # SQLite:
    cp db.sqlite3 /tmp/db_backup_$(date +%Y%m%d_%H%M%S).sqlite3
    cp -r */migrations /tmp/migrations_backup_$(date +%Y%m%d_%H%M%S)/
    python manage.py showmigrations > /tmp/migrations_before.txt

### Before editing an existing migration file
NEVER edit a migration that has been applied anywhere. Create a new migration instead.

### Before destructive model change
    # Check the field has no data you need:
    python manage.py shell -c "from app.models import M; print(M.objects.exclude(field=None).count())"
    # Generate migration but DON'T apply yet:
    python manage.py makemigrations --name remove_old_field app
    # Review the file manually before running migrate

### Before bulk data ops
    python manage.py dumpdata myapp > /tmp/myapp_$(date +%Y%m%d_%H%M%S).json

## DIAGNOSTIC RECIPES

### When Migration Fails
    1. Read full traceback, find the exact migration file + operation
    2. python manage.py showmigrations 2>&1 | grep "\[ \]"  # unapplied
    3. If InconsistentMigrationHistory:
       a. Compare DB state with git log of migrations/
       b. If migration in DB but not git: python manage.py migrate --fake app 0003_name
    4. If migration partial-applied:
       a. Restore from backup: psql $DATABASE_URL < /tmp/db_backup_TIMESTAMP.sql
       b. Fix the operation
       c. Re-run: python manage.py migrate
    5. Verify: python manage.py check --deploy

### When DRF Returns 403 Unexpectedly
    1. Check DEFAULT_PERMISSION_CLASSES in settings
    2. Check view-level permission_classes override
    3. CSRF: for non-Session auth (JWT, Token), CSRF not required
    4. Temporarily set permission_classes = [permissions.AllowAny]
       If 403 disappears, it's permissions; if not, it's authentication
    5. Print request.user.is_authenticated inside the view

### When Queries Are Slow
    1. django-debug-toolbar in dev, check SQL panel
    2. print(MyModel.objects.filter(...).query)  # see actual SQL
    3. EXPLAIN ANALYZE in psql on the SQL
    4. Fixes: select_related, prefetch_related, db_index=True, .iterator()

### When makemigrations Detects No Changes
    1. App in INSTALLED_APPS?
    2. Model imported in models/__init__.py?
    3. Duplicate model definition or import shadowing?
    4. python manage.py shell -c "from app.models import M; print(M._meta.fields)"

### When Celery Tasks Don't Run
    1. redis-cli ping  -> PONG
    2. CELERY_BROKER_URL matches broker?
    3. celery -A config inspect active
    4. celery -A config inspect registered
    5. Test sync: from app.tasks import t; t.apply(args=[...])

## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| InconsistentMigrationHistory | DB and migrations out of sync | migrate --fake app migration_name |
| RuntimeWarning naive datetime | datetime.now() with USE_TZ | timezone.now() |
| IntegrityError NOT NULL | bulk_create missing field | Provide value or default= |
| RelatedObjectDoesNotExist | Reverse OneToOne missing | hasattr check or try/except |
| You cannot call this from async context | ORM in async view | await sync_to_async(call)() |
| Missing staticfiles manifest | collectstatic not run | Run before deploy |
| CORS blocked | Middleware order or origin | Fix order, add to CORS_ALLOWED_ORIGINS |
| get() returned more than one | Duplicates in data | filter().first() or unique constraint |
| Circular import | Models <-> signals | Import inside function, use AppConfig.ready() |

## Anti-Patterns

### NEVER put logic in serializers beyond data shaping
Belongs in services. Otherwise unreachable from management commands, Celery tasks, tests.

### NEVER use filter().exists() + filter().first() (two queries)
    post = Post.objects.filter(slug=slug).first()
    if post: ...

### NEVER catch bare except Exception in views
Swallows programming mistakes. Catch specific exceptions. Let unexpected propagate.

### NEVER use Model.objects.all() without pagination in views
Loads everything into memory. 1M rows = OOM. ALWAYS paginate.

### NEVER store sensitive data in sessions
Session data not encrypted at rest by default.

### NEVER use raw() with f-strings (SQL injection)
Always parameterize: raw("SELECT ... WHERE slug = %s", [user_input])

### NEVER run makemigrations in production
Production must have pre-committed, reviewed migrations only.

### NEVER use GenericForeignKey unless no alternative
Bypasses ORM optimizations, breaks referential integrity, hard to reason about.

## Production Checklist

- Custom User model created BEFORE first migration
- AUTH_USER_MODEL set in settings.py
- No django.contrib.auth.models.User reference anywhere
- SECRET_KEY from env var, never hardcoded
- DEBUG = False in production
- ALLOWED_HOSTS explicit (no wildcards)
- DATABASES from DATABASE_URL env var
- All migrations committed and reviewed before deploy
- python manage.py migrate --check passes in CI before app starts
- python manage.py check --deploy passes
- collectstatic run during build
- STATIC_ROOT and MEDIA_ROOT served by nginx/whitenoise
- CORS_ALLOWED_ORIGINS = exact frontend origin (no wildcard)
- CSRF_TRUSTED_ORIGINS set if HTTPS + SessionAuthentication
- File uploads validated for type and size
- DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
- USE_TZ = True and TIME_ZONE set
- Logging configured (Sentry or ADMINS)
- CELERY_TASK_ALWAYS_EAGER = False in prod
- PgBouncer for PostgreSQL connection pooling
- No print() in production code (use logging)
- Sensitive fields excluded from serializer output
- Rate limiting on auth endpoints (django-ratelimit or nginx)
- Security headers: SECURE_HSTS_SECONDS, SECURE_SSL_REDIRECT, etc.
