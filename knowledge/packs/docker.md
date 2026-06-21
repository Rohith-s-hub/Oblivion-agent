# Docker Knowledge Pack

## CRITICAL: Layer Caching and Build Context

Docker builds layers sequentially. EVERY instruction creates a new layer. Layers are
cached and reused ONLY if the instruction AND all previous instructions are identical.
NEVER put frequently-changing files early in the Dockerfile.
ALWAYS order instructions from least-changed to most-changed.

CRITICAL ordering for cache efficiency:

    FROM base_image
    # 1. System packages (rarely change)
    RUN apt-get update && apt-get install -y package1 package2
    # 2. Dependency manifests ONLY (package.json, requirements.txt)
    COPY package.json package-lock.json ./
    # 3. Install dependencies
    RUN npm install
    # 4. Application code (changes frequently)
    COPY . .
    # 5. Build artifacts
    RUN npm run build

NEVER do COPY . . before installing dependencies. Breaks cache on EVERY code change.

Build context is EVERYTHING in the directory where you run docker build. A 5GB
node_modules in context makes builds slow even if Dockerfile never touches it.
ALWAYS use .dockerignore.


## Project Setup

### Install Docker (Ubuntu/Debian)
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    # Log out and back in for group changes

### Essential .dockerignore (CREATE BEFORE FIRST BUILD)
    node_modules
    npm-debug.log
    .git
    .gitignore
    .env
    .env.local
    .venv
    __pycache__
    *.pyc
    .pytest_cache
    .coverage
    dist
    build
    *.egg-info
    .DS_Store
    *.log
    .idea
    .vscode

### Verify Installation
    docker run hello-world
    docker --version
    docker compose version

If docker compose (v2) fails:
    sudo apt-get install docker-compose-plugin


## CRITICAL: Common Foot-Guns

### 1. Build Context Size Explosion
ALWAYS check context size:
    du -sh .  # if > 100MB, audit what's included

ALWAYS create .dockerignore BEFORE first build. Without it, builds are 10-100x slower.

### 2. Layer Cache Invalidation from Timestamps
COPY invalidates cache if ANY file timestamp changes, even if content identical.

    # WRONG - cache breaks on any file change
    COPY . .
    RUN npm install

    # CORRECT - cache preserved if package.json unchanged
    COPY package.json package-lock.json ./
    RUN npm install
    COPY . .

### 3. Root User in Containers (SECURITY RISK)
Containers run as root by default. Process escapes get root on host.

    # ALWAYS create non-root user
    FROM node:20
    RUN groupadd -r appuser && useradd -r -g appuser appuser
    USER appuser
    WORKDIR /home/appuser/app
    COPY --chown=appuser:appuser . .

    # For Python:
    FROM python:3.12
    RUN useradd -m -u 1000 appuser
    USER appuser

### 4. Unbounded Image Size
Each RUN creates a layer. Deleted files in later layers still exist in earlier layers.

    # WRONG - downloads stay in layer 1
    RUN apt-get update && apt-get install -y wget
    RUN wget http://example.com/huge.tar.gz
    RUN rm huge.tar.gz  # still in layer 2

    # CORRECT - cleanup in same layer
    RUN apt-get update && apt-get install -y wget \
        && wget http://example.com/huge.tar.gz \
        && tar -xzf huge.tar.gz \
        && rm huge.tar.gz \
        && apt-get clean && rm -rf /var/lib/apt/lists/*

### 5. Port Binding Conflicts
docker run -p 3000:3000 fails silently if port bound. Container runs but inaccessible.

    lsof -i :3000     # find what's holding the port
    netstat -tuln | grep 3000
    # Use different host port: docker run -p 3001:3000 myapp

### 6. Volume Permission Mismatches
Bind mounts reflect host permissions, causing EACCES in container.

    # For bind mounts with non-root user
    sudo chown -R 1000:1000 ./data
    docker run -v $(pwd)/data:/app/data myapp

    # For named volumes (created as root by default)
    COPY --chown=appuser:appuser ./initial-data /app/data

### 7. Environment Variable Escaping
Shell expansion differs between Dockerfile and scripts.

    # Expands at BUILD time using build host env
    RUN echo "Home is $HOME"

    # Literal string, no expansion
    RUN echo 'Home is $HOME'

    # Use ENV for runtime variables
    ENV HOME=/home/appuser
    RUN echo "Home is $HOME"

### 8. Multi-Stage Build Artifacts
COPY --from=builder copies from earlier stage. If source path missing, build succeeds
but copies nothing, creating broken image.

    # ALWAYS verify artifacts
    FROM builder AS build
    RUN npm run build
    RUN test -f /app/dist/index.html || exit 1

    FROM nginx
    COPY --from=build /app/dist /usr/share/nginx/html
    RUN test -f /usr/share/nginx/html/index.html || exit 1


## File Templates

### Multi-Stage Node.js Production Dockerfile
    FROM node:20-alpine AS base
    ENV NODE_ENV=production
    WORKDIR /app

    FROM base AS deps
    COPY package.json package-lock.json ./
    RUN npm ci --only=production

    FROM base AS build
    COPY package.json package-lock.json ./
    RUN npm ci
    COPY . .
    RUN npm run build

    FROM base AS runtime
    RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001
    COPY --from=deps --chown=nodejs:nodejs /app/node_modules ./node_modules
    COPY --from=build --chown=nodejs:nodejs /app/dist ./dist
    COPY --chown=nodejs:nodejs package.json ./
    USER nodejs
    EXPOSE 3000
    HEALTHCHECK --interval=30s --timeout=3s CMD wget -q --spider http://localhost:3000/health || exit 1
    CMD ["node", "dist/index.js"]

### Python FastAPI Production Dockerfile
    FROM python:3.12-slim AS base
    ENV PYTHONUNBUFFERED=1 \
        PYTHONDONTWRITEBYTECODE=1 \
        PIP_NO_CACHE_DIR=1 \
        PIP_DISABLE_PIP_VERSION_CHECK=1
    WORKDIR /app

    FROM base AS builder
    RUN apt-get update && apt-get install -y --no-install-recommends gcc \
        && rm -rf /var/lib/apt/lists/*
    COPY requirements.txt .
    RUN pip install --user -r requirements.txt

    FROM base AS runtime
    RUN useradd -m -u 1000 appuser
    COPY --from=builder /root/.local /home/appuser/.local
    COPY --chown=appuser:appuser . .
    USER appuser
    ENV PATH=/home/appuser/.local/bin:$PATH
    EXPOSE 8000
    HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1
    CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

### Docker Compose for Development
    version: '3.8'

    services:
      app:
        build:
          context: .
          dockerfile: Dockerfile.dev
        ports:
          - "3000:3000"
        volumes:
          - .:/app
          - /app/node_modules         # CRITICAL: preserves container's node_modules
        environment:
          - NODE_ENV=development
          - DATABASE_URL=postgresql://postgres:postgres@db:5432/myapp
        depends_on:
          db:
            condition: service_healthy
        command: npm run dev

      db:
        image: postgres:15-alpine
        ports:
          - "5432:5432"
        environment:
          - POSTGRES_USER=postgres
          - POSTGRES_PASSWORD=postgres
          - POSTGRES_DB=myapp
        volumes:
          - postgres_data:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U postgres"]
          interval: 5s
          timeout: 5s
          retries: 5

      redis:
        image: redis:7-alpine
        volumes:
          - redis_data:/data

    volumes:
      postgres_data:
      redis_data:

### Docker Compose for Production (key additions)
    services:
      app:
        image: myapp:${VERSION:-latest}
        restart: unless-stopped
        env_file: .env.production
        healthcheck:
          test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/health"]
          interval: 30s
          timeout: 10s
          retries: 3
          start_period: 40s
        deploy:
          resources:
            limits:
              cpus: '2'
              memory: 2G
            reservations:
              cpus: '1'
              memory: 1G


## Patterns

### Multi-Stage Builds for Size Reduction
Final image should contain ONLY runtime dependencies and artifacts.

    # Builder stage (1GB+)
    FROM golang:1.21 AS builder
    WORKDIR /src
    COPY go.mod go.sum ./
    RUN go mod download
    COPY . .
    RUN CGO_ENABLED=0 GOOS=linux go build -o /app/server

    # Runtime stage (15MB final)
    FROM alpine:3.18
    RUN apk add --no-cache ca-certificates
    COPY --from=builder /app/server /server
    EXPOSE 8080
    CMD ["/server"]

### Health Checks (Production Critical)
    # HTTP services
    HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
      CMD curl -f http://localhost:3000/health || exit 1

    # PostgreSQL
    HEALTHCHECK CMD pg_isready -U postgres || exit 1

    # Redis
    HEALTHCHECK CMD redis-cli ping || exit 1

### Secrets Management
NEVER put secrets in Dockerfile or image layers.

    # Build-time secrets (BuildKit required)
    RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm install
    # Build with:
    docker buildx build --secret id=npmrc,src=$HOME/.npmrc .

    # Runtime secrets
    docker run -e DATABASE_PASSWORD=$(cat db_password.txt) myapp
    docker run --env-file .env.production myapp

### Volume Mount Strategies
    # Development: live code reload
    docker run -v $(pwd):/app myapp

    # Production: named volume for data
    docker run -v pgdata:/var/lib/postgresql/data postgres

    # Prevent node_modules override in dev (CRITICAL)
    docker run -v $(pwd):/app -v /app/node_modules myapp

### Network Isolation
    docker network create myapp-network
    docker run --network myapp-network --name db postgres
    docker run --network myapp-network --name app myapp

    # App reaches db by hostname 'db'
    DATABASE_URL=postgresql://postgres@db:5432/myapp

In docker-compose, services on same network communicate by service name.

### Build Arguments
    ARG NODE_VERSION=20
    FROM node:${NODE_VERSION}-alpine
    ARG BUILD_DATE
    ARG VERSION
    LABEL version=${VERSION}

    # Build with:
    docker build --build-arg NODE_VERSION=18 --build-arg VERSION=1.2.3 .

NEVER use ARG for secrets - visible in docker history.


## EDGE CASES AND GOTCHAS

### 1. COPY --chown Doesn't Work on Windows Docker
On Windows Docker Desktop, files copied as root despite --chown. Workaround:
    COPY . .
    RUN chown -R appuser:appuser /app

### 2. Alpine vs Debian DNS Resolution
Alpine uses musl libc - handles DNS differently. For production Node.js, prefer Debian:
    # Prefer this for Node.js
    FROM node:20-slim
    # Not this (unless you know why)
    FROM node:20-alpine

### 3. Volume Mounts Override COPY in Dockerfile
If Dockerfile does COPY ./data /app/data and you mount -v $(pwd)/empty:/app/data,
the mount OVERRIDES copied files. Container sees empty directory.

In docker-compose:
    volumes:
      - ./src:/app/src         # overrides /app/src from image
      - /app/node_modules      # preserves node_modules from image

### 4. WORKDIR Creates Directory as Root
WORKDIR creates dir if missing, owned by root. Switching to non-root user breaks writes.

    # CORRECT pattern
    RUN mkdir -p /app && chown appuser:appuser /app
    USER appuser
    WORKDIR /app

### 5. ENV Variables Don't Expand in ENTRYPOINT Exec Form
    ENV PORT=8080
    ENTRYPOINT ["./server", "--port", "$PORT"]  # $PORT is literal!

    # Use shell form for expansion
    ENTRYPOINT ./server --port $PORT
    # Or sh -c
    ENTRYPOINT ["sh", "-c", "./server --port $PORT"]

### 6. Docker BuildKit Required for Advanced Features
RUN --mount, COPY --link need BuildKit. Enable with:
    export DOCKER_BUILDKIT=1
    docker build .
    # docker-compose:
    COMPOSE_DOCKER_CLI_BUILD=1 DOCKER_BUILDKIT=1 docker-compose build

### 7. Layer Caching Breaks Across Hosts
Building on CI then locally = full rebuild. Use registry cache:
    docker build --push --cache-to type=registry,ref=myregistry/myapp:cache .
    docker build --cache-from type=registry,ref=myregistry/myapp:cache .

### 8. Bind Mount Absolute Path Required
    # WRONG - creates named volume named "."
    docker run -v .:app myapp

    # CORRECT
    docker run -v $(pwd):/app myapp
    docker run -v ${PWD}:/app myapp  # Windows

### 9. Signal Handling with PID 1
Process with PID 1 doesn't receive signals normally. SIGTERM ignored.

    # Install tini
    RUN apt-get install -y tini
    ENTRYPOINT ["/usr/bin/tini", "--"]
    CMD ["node", "server.js"]

    # OR use --init flag
    docker run --init myapp

### 10. BuildKit Removes Intermediate Containers
Can't debug failed RUN steps with BuildKit. Disable temporarily:
    DOCKER_BUILDKIT=0 docker build .
    docker ps -a
    docker commit <container_id> debug-image
    docker run -it debug-image sh

### 11. Localhost is the Container Itself
    # WRONG inside docker-compose
    DATABASE_URL=postgresql://localhost:5432/myapp

    # CORRECT - use service name
    DATABASE_URL=postgresql://db:5432/myapp

### 12. Anonymous Volumes Persist After Container Deletion
Dockerfile VOLUME without explicit mount creates anonymous volumes that orphan.
ALWAYS use named volumes or bind mounts explicitly.


## BACKUP-BEFORE-CHANGE Protocol

### Before Updating Base Image Version
    docker tag myapp:latest myapp:backup-$(date +%Y%m%d)
    docker save myapp:latest > myapp-backup.tar
    # Update Dockerfile FROM line
    docker build -t myapp:test .
    docker run myapp:test
    # If broken, restore:
    docker load < myapp-backup.tar

### Before Changing docker-compose.yml
    cp docker-compose.yml docker-compose.yml.backup
    docker-compose ps > compose-state-before.txt
    docker-compose config > compose-resolved-before.yml
    # After changes, verify:
    docker-compose config
    docker-compose up -d

### Before Pruning Images/Volumes
    # Dry-run first
    docker image prune -a --filter "until=24h" --dry-run
    docker volume prune --dry-run
    # Backup critical volumes
    docker run --rm -v pgdata:/data -v $(pwd):/backup alpine \
        tar czf /backup/pgdata-backup.tar.gz -C /data .
    # Now safe to prune
    docker image prune -a --filter "until=24h"

### Before Updating Compose Services
    # Backup all volumes
    for vol in $(docker volume ls -q); do
      docker run --rm -v $vol:/data -v $(pwd)/backups:/backup alpine \
        tar czf /backup/$vol-$(date +%Y%m%d).tar.gz -C /data .
    done
    docker-compose down
    docker-compose pull
    docker-compose up -d

### Before Major Dockerfile Refactor
    git checkout -b dockerfile-refactor
    git add Dockerfile
    git commit -m "backup: dockerfile before refactor"
    docker build -t myapp:pre-refactor .
    # ... refactor ...
    docker build -t myapp:test .
    docker images myapp                # compare sizes
    docker history myapp:pre-refactor  # compare layers
    docker history myapp:test


## DIAGNOSTIC RECIPES

### When Build is Extremely Slow
    1. Check build context size:
       du -sh .
       find . -type f | wc -l
    2. Review .dockerignore (ensure node_modules, .git, venv excluded)
    3. Check layer cache efficiency:
       docker build --progress=plain .
       # Look for CACHED vs RUN
    4. Identify slow steps:
       time docker build --no-cache --progress=plain . 2>&1 | tee build.log
    5. Optimize Dockerfile order (deps before code)

### When Container Exits Immediately
    1. Check logs: docker logs <container_id>
    2. Run with shell:
       docker run -it --entrypoint sh myapp
    3. Check CMD/ENTRYPOINT:
       docker inspect myapp | grep -A 10 Cmd
    4. Verify executable:
       docker run -it myapp ls -la /app/server
       docker run -it myapp file /app/server
    5. Check missing dependencies:
       docker run -it myapp ldd /app/server

### When Volume Data is Missing
    1. List volumes: docker volume ls
    2. Check mount point:
       docker inspect <container_id> | grep Mounts -A 20
    3. Verify data in volume:
       docker run --rm -v <volume_name>:/data alpine ls -la /data
    4. Check ownership:
       docker run --rm -v <volume_name>:/data alpine ls -ln /data
    5. Restore from backup if empty

### When Network Connectivity Fails Between Containers
    1. Verify same network:
       docker network inspect <network_name>
    2. Test DNS:
       docker exec app ping db
       docker exec app nslookup db
    3. Test from inside:
       docker exec app curl http://db:5432
    4. Check firewall (Linux):
       sudo iptables -L -n
       sudo ufw status

### When Build Fails "No Space Left on Device"
    1. df -h && docker system df
    2. Clean build cache: docker builder prune --all
    3. Remove unused images: docker image prune -a
    4. Remove stopped containers: docker container prune
    5. Remove unused volumes: docker volume prune

### When Permission Denied in Container
    1. Check ownership: docker exec <container> ls -la /app
    2. Check user: docker exec <container> whoami
    3. Check Dockerfile USER: docker history myapp | grep USER
    4. Temporary fix: docker exec -u root <container> chown -R appuser:appuser /app
    5. Permanent fix in Dockerfile:
       COPY --chown=appuser:appuser . /app


## COMMON ERRORS

| Error | Cause | Fix |
|---|---|---|
| error checking context: can't stat | File in .dockerignore still referenced | Remove reference or fix .dockerignore path |
| failed to solve: exit code 137 | Out of memory during build | Increase Docker memory limit or close apps |
| COPY failed: no source files | COPY source path doesn't exist | Verify path; check .dockerignore not excluding |
| unable to evaluate symlinks | Symlink points outside build context | Copy actual files or include target in context |
| denied: requested access denied | Not authenticated to registry | docker login with correct credentials |
| pull access denied, repo doesn't exist | Image name typo or private repo | Verify name; authenticate if private |
| container name already in use | Container with name exists | docker rm <name> or use different name |
| port is already allocated | Port in use on host | lsof -i :PORT; kill or use different port |
| Mounts denied (Mac/Windows) | File sharing not enabled | Enable in Docker Desktop preferences |
| exec user process no such file | Entrypoint has CRLF line endings | dos2unix entrypoint.sh |
| mkdir permission denied | Host dir missing or no permission | mkdir -p; fix permissions |
| ApplyLayer operation not permitted | SELinux blocks operation | Add :z or :Z to volume: -v ./data:/app/data:z |
| Invalid interpolation format | Env var syntax error in compose | Use ${VAR} not $VAR; escape literal with $$ |
| pull access denied for myapp | Image only exists locally | Build first; or push to registry |


## Anti-Patterns

### NEVER split apt-get update and install
    # WRONG - update cached, install gets stale lists
    RUN apt-get update
    RUN apt-get install -y curl

    # CORRECT
    RUN apt-get update && apt-get install -y curl \
        && apt-get clean && rm -rf /var/lib/apt/lists/*

### NEVER use :latest tag in production
    # WRONG - unpredictable, breaks retroactively
    FROM node:latest
    # CORRECT
    FROM node:20.11.0-alpine3.19

### NEVER install as root then switch user
    # WRONG - vulnerabilities in build process
    FROM node:20
    COPY package.json .
    RUN npm install       # as root
    USER node

    # CORRECT
    FROM node:20
    RUN mkdir /app && chown node:node /app
    WORKDIR /app
    USER node
    COPY --chown=node:node package.json .
    RUN npm install

### NEVER put secrets in ENV or LABEL
    # WRONG - in image history forever
    ENV DATABASE_PASSWORD=secret
    LABEL api_key="sk-1234"

    # CORRECT - runtime injection
    docker run -e DATABASE_PASSWORD=... myapp

### NEVER use ADD when COPY suffices
    # WRONG - ADD auto-extracts tar, can fetch URLs
    ADD . /app
    # CORRECT - explicit
    COPY . /app

### NEVER hardcode localhost for inter-container communication
    # WRONG
    DATABASE_URL=postgresql://localhost:5432/myapp
    # CORRECT
    DATABASE_URL=postgresql://db:5432/myapp

### NEVER run stateful databases in containers without orchestration
For production: use Kubernetes StatefulSets or managed services (RDS, etc).
Plain docker run with volumes lacks HA, backups, replication.

### NEVER ignore exit codes in health checks
    # WRONG - always succeeds even on failure
    HEALTHCHECK CMD curl http://localhost:8000/health
    # CORRECT
    HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1

### NEVER use sleep to wait for dependencies
    # WRONG - arbitrary, brittle
    CMD sleep 10 && npm start
    # CORRECT - wait for actual readiness
    CMD wait-for-it db:5432 -- npm start
    # OR use depends_on with healthcheck in docker-compose


## Production Checklist

### Image Security
- Base image from official source, pinned version (not :latest)
- Non-root user defined with USER directive
- No secrets in image layers (verify with docker history)
- Minimal base image (alpine, slim, distroless)
- Security scanning done (docker scan or Trivy)
- HEALTHCHECK defined for all services
- Read-only root filesystem where possible

### Build Optimization
- .dockerignore created and comprehensive
- Multi-stage build for compiled languages
- Dependency installation before code COPY
- Single RUN for apt-get update && install && cleanup
- Build cache optimized (least-changed first)
- Image size under 500MB for apps
- BuildKit enabled

### Runtime Configuration
- Resource limits defined (memory, CPU)
- Restart policy configured (unless-stopped or on-failure)
- Environment variables externalized
- Logging driver configured (json-file with rotation)
- Network isolation (custom networks, not bridge)
- Volumes for persistent data explicitly named
- Health checks passing before marking ready
- Graceful shutdown handling (SIGTERM caught)

### Docker Compose Production
- Version pinned in image tags
- depends_on uses healthcheck conditions
- All services have restart policies
- Secrets via docker secrets or env files (not in git)
- Resource limits in deploy section
- Volumes backed up with documented procedure
- Port mappings minimized

### Monitoring
- Logs accessible and aggregated
- Metrics exported (Prometheus, StatsD)
- Health endpoint returns meaningful status
- Dead container removal automated
- Image pruning scheduled
- Volume backup automated and tested
- Update strategy documented (rolling, blue-green)
- Rollback procedure tested
