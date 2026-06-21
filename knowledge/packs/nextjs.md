# Next.js Knowledge Pack

## CRITICAL: Modern Next.js (14/15) Uses App Router

- App Router is THE default (the /app directory)
- Pages Router (/pages directory) is LEGACY - avoid for new projects
- Server Components by default, Client Components opt-in with "use client"

## Project Setup

    npx create-next-app@latest my-app --typescript --tailwind --app

## CRITICAL: package.json scripts

    {
      "scripts": {
        "dev": "next dev",
        "build": "next build",
        "start": "next start",
        "lint": "next lint"
      }
    }

## Starting the Dev Server

    start_server(command="npm run dev", port=3000, wait_seconds=10)

Custom port:

    start_server(command="npx next dev -p 3001", port=3001, wait_seconds=10)

Bind to all interfaces (WSL/Docker):

    start_server(command="npx next dev -H 0.0.0.0", port=3000, wait_seconds=10)

## App Router Structure

    my-app/
    ├── package.json
    ├── next.config.js
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── public/
    └── app/
        ├── layout.tsx
        ├── page.tsx
        ├── globals.css
        ├── about/
        │   └── page.tsx
        ├── blog/
        │   ├── page.tsx
        │   └── [slug]/
        │       └── page.tsx
        └── api/
            └── hello/
                └── route.ts

## CRITICAL: app/layout.tsx Template

    import './globals.css'

    export const metadata = {
      title: 'My App',
      description: 'Built with Next.js',
    }

    export default function RootLayout({ children }) {
      return (
        <html lang="en">
          <body>{children}</body>
        </html>
      )
    }

## CRITICAL: app/page.tsx Template

    export default function HomePage() {
      return (
        <main>
          <h1>Hello, Next.js!</h1>
        </main>
      )
    }

## Server vs Client Components

Server Components (default):
- Run on server only, never shipped to browser
- Can use async/await directly: const data = await fetch(...)
- Cannot use useState, useEffect, browser APIs
- Better performance

Client Components (opt-in):
- Add "use client" at the top of the file
- Can use hooks, browser APIs, event handlers
- Use for interactivity (forms, animations, etc.)

Example client component:

    "use client"
    import { useState } from 'react'
    export default function Counter() {
      const [n, setN] = useState(0)
      return <button onClick={() => setN(n+1)}>{n}</button>
    }

## API Routes (Route Handlers)

    // app/api/users/route.ts
    import { NextResponse } from 'next/server'

    export async function GET() {
      return NextResponse.json({ users: [] })
    }

    export async function POST(request) {
      const body = await request.json()
      return NextResponse.json({ created: body })
    }

## Common Errors

| Error | Fix |
|---|---|
| Hydration mismatch | Don't use Date.now() or Math.random() in server components |
| useState only in Client | Add "use client" at top of file |
| Module not found next/font | Use import { Inter } from 'next/font/google' |
| Port 3000 in use | npx next dev -p 3001 |
| Error: Image domains | Add domain to next.config.js images.remotePatterns |
