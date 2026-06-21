# React Knowledge Pack

## CRITICAL: Modern React Project Setup (2024+)

- ALWAYS use Vite, never Create React App (CRA is deprecated)
- Entry point: src/main.jsx (or .tsx for TypeScript) - NEVER public/index.html
- index.html lives in PROJECT ROOT (not in public/)
- Default Vite port: 5173 (override via vite.config.js)

## CRITICAL: Vite Config (THE COMMON SERVER BUG)

The #1 reason "localhost refused to connect" happens with React is the host binding.

vite.config.js CORRECT PATTERN:

    import { defineConfig } from 'vite'
    import react from '@vitejs/plugin-react'

    export default defineConfig({
      plugins: [react()],
      server: {
        port: 3000,
        host: true,
        strictPort: false,
        open: false
      }
    })

WHY host: true: Without it, Vite binds only 127.0.0.1, which breaks in WSL,
Docker, cloud VMs, and sometimes Linux desktops. ALWAYS set host: true.

## CRITICAL: package.json Scripts

    {
      "name": "my-app",
      "private": true,
      "version": "0.0.0",
      "type": "module",
      "scripts": {
        "dev": "vite",
        "build": "vite build",
        "preview": "vite preview"
      },
      "dependencies": {
        "react": "^18.3.0",
        "react-dom": "^18.3.0"
      },
      "devDependencies": {
        "@vitejs/plugin-react": "^4.3.0",
        "vite": "^5.4.0"
      }
    }

## CRITICAL: index.html Template (in project root)

    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>App</title>
      </head>
      <body>
        <div id="root"></div>
        <script type="module" src="/src/main.jsx"></script>
      </body>
    </html>

## CRITICAL: src/main.jsx Template

    import React from 'react'
    import ReactDOM from 'react-dom/client'
    import App from './App'
    import './index.css'

    ReactDOM.createRoot(document.getElementById('root')).render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    )

## How to Start the Dev Server (CORRECT)

Use the agent's start_server tool:

    start_server(command="npm run dev", port=3000, wait_seconds=8)

Or with explicit host flag if vite.config.js missing:

    start_server(command="npx vite --host --port 3000", port=3000, wait_seconds=8)

DO NOT use http-server for React apps - it only serves static files, not JSX.
DO NOT use python -m http.server - same problem.

## Patterns

- Components: Function components only. No class components.
- State (local): useState, useReducer
- State (global): Zustand (simple) or Redux Toolkit. Avoid plain Redux.
- Effects: useEffect with proper dependency arrays
- Routing: react-router-dom v6 - use Routes + Route element. v5 syntax is DEAD.
- Data fetching: TanStack Query (formerly React Query). Don't roll your own.
- Forms: React Hook Form (simple) or Formik (complex)
- Styling: Tailwind CSS, CSS Modules, or styled-components.

## Folder Layout (RECOMMENDED)

    my-app/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── public/
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── index.css
        ├── components/
        ├── pages/
        ├── hooks/
        ├── services/
        ├── store/
        └── utils/

## COMMON ERRORS AND FIXES

| Error | Cause | Fix |
|---|---|---|
| localhost refused to connect | Vite bound to 127.0.0.1 only | Set server.host: true in vite.config.js |
| Module not found vite/client | Missing types in TS | Add reference comment to src/vite-env.d.ts |
| process is not defined | Used Node API in browser | Use import.meta.env.VITE_FOO instead |
| Cannot find module 'react' | Forgot npm install | Run npm install first |
| Failed to load url /src/main.tsx | index.html points wrong | Match extension: jsx for JS, tsx for TS |
| Blank white page | Build error swallowed | Check browser console and Vite terminal |

## Env Variables (Vite)

- Files: .env, .env.local, .env.production
- MUST prefix with VITE_ to expose to client: VITE_API_URL=https://api.example.com
- Access in code: import.meta.env.VITE_API_URL
- NEVER put secrets here - .env is shipped to the client
