# Deployment Knowledge Pack

## CRITICAL: Production Build vs Dev Server

NEVER ship npm run dev to production. Always:

    npm run build        # produces /dist or /.next
    npm run preview      # Vite - preview prod build locally
    npm run start        # Next.js - runs production server

## Static Site Hosts (No Server Needed)

For Vite/React/Vue static builds:
- Vercel - vercel deploy (auto-detects framework)
- Netlify - drop /dist folder or connect Git
- Cloudflare Pages - connect Git, build: npm run build, output: dist
- GitHub Pages - npm run build, push /dist to gh-pages branch

## Full-Stack Hosts

- Vercel - Next.js (best fit), full-stack
- Railway - easy Postgres + apps
- Fly.io - Docker-based, edge locations
- Render - easy free tier
- Cloudflare Workers - edge functions

## Environment Variables in Production

NEVER commit secrets to git. Use:

    # .env.local (gitignored)
    DATABASE_URL=postgresql://...
    API_KEY=sk_live_...

Then on host:
- Vercel: Settings -> Environment Variables
- Railway: Variables tab
- Fly.io: fly secrets set DATABASE_URL=...

## nginx Config for SPA (React/Vue)

    server {
      listen 80;
      server_name myapp.com;
      root /usr/share/nginx/html;
      index index.html;

      location / {
        try_files $uri $uri/ /index.html;
      }

      location /api/ {
        proxy_pass http://backend:8000/;
        proxy_set_header Host $host;
      }
    }

The try_files line is CRITICAL for SPAs - without it, refresh on /about gives 404.

## Docker for React/Vue (multi-stage)

    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package*.json ./
    RUN npm ci
    COPY . .
    RUN npm run build

    FROM nginx:alpine
    COPY --from=builder /app/dist /usr/share/nginx/html
    EXPOSE 80
    CMD ["nginx", "-g", "daemon off;"]
