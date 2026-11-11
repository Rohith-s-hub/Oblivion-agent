# Deployment & Hosting Knowledge Pack

## Static Sites / React-Vite Frontends

### Vercel (recommended default for React/Vite/Next.js)
1. Push code to GitHub.
2. Import the repo at vercel.com — auto-detects Vite/Next.js/React.
3. Build command: `npm run build` (Vite) — output dir: `dist`.
4. Env vars: set in Vercel dashboard → Settings → Environment Variables. For Vite, they MUST be prefixed `VITE_` to be exposed to the client.
5. Auto-deploys on every push to `main`; PR previews on every branch.

### Netlify (equally solid alternative)
- Build command: `npm run build`, publish directory: `dist` (Vite) or `build` (CRA).
- `netlify.toml` for redirects (needed for client-side routing / React Router):
```toml
  [[redirects]]
    from = "/*"
    to = "/index.html"
    status = 200
```
  Without this, refreshing any non-root route (e.g. `/about`) 404s.

### GitHub Pages (free, good for portfolios/static-only, no server-side)
    npm run build
    # then push the `dist` folder to a `gh-pages` branch, or use:
    npm install -D gh-pages
    # add to package.json scripts: "deploy": "gh-pages -d dist"
    npm run deploy
- Vite apps need `base: '/<repo-name>/'` in `vite.config.js` if deployed to `username.github.io/repo-name` (not needed for a custom domain or `username.github.io` root repo).

## Backend / Full-Stack Hosting

### Render / Railway (simple Node/Python backend hosting)
- Connect GitHub repo, set build + start commands (e.g. `npm install` / `npm start`, or `pip install -r requirements.txt` / `uvicorn main:app`).
- Set env vars in the dashboard — never commit `.env` to the repo.
- Free tiers often spin down on inactivity — first request after idle is slow (cold start).

### Docker-based deployment (any VPS / cloud provider)
- If a Dockerfile exists, most platforms (Render, Railway, Fly.io, AWS) can build directly from it — no need to duplicate build config.
- Basic flow: `docker build -t app .` → `docker run -p 8080:8080 app` locally to verify before pushing.

## Environment Variables (cross-cutting)
- NEVER commit `.env` — confirm it's in `.gitignore` before first commit.
- Client-exposed vars (Vite: `VITE_*`, Next.js: `NEXT_PUBLIC_*`) are PUBLIC — never put secrets there, only public config (API base URLs, feature flags).
- True secrets (API keys, DB passwords) belong ONLY in the hosting platform's dashboard/env settings, read server-side.

## Custom Domains
- Add domain in the hosting platform's dashboard.
- Point DNS: either an `A` record to the platform's IP, or a `CNAME` to the platform's provided hostname (most modern platforms use CNAME).
- Propagation can take up to 24-48h; use `dig <domain>` or `nslookup <domain>` to check current DNS resolution while waiting.

## "Works locally but broken when deployed" — Diagnosis Checklist
1. **Blank page / white screen** → open browser devtools console on the LIVE site (not local) — almost always a JS error or a wrong asset path.
2. **404 on page refresh for non-root routes** → missing SPA redirect rule (see Netlify config above) — the host is looking for a real file at that path instead of serving `index.html`.
3. **API calls failing (CORS/network error)** → the deployed frontend is likely calling `localhost:xxxx` instead of the deployed backend URL — check env vars actually got set on the HOSTING platform, not just locally.
4. **"process is not defined" or similar in browser** → Node-only code leaked into client bundle — check for accidental use of `process.env` instead of `import.meta.env` (Vite) in client code.
5. **Build succeeds locally, fails on host** → check Node version mismatch — pin it via `.nvmrc` or the platform's Node-version setting; also check for case-sensitivity bugs (macOS/Windows filesystems are case-insensitive, Linux hosts are not — `import './Button'` vs actual file `button.jsx` breaks only in prod).
6. **Env var seemingly "not working"** → for Vite/CRA-style tools, env vars are baked in at BUILD time, not read at runtime — changing them requires a rebuild/redeploy, not just a server restart.
