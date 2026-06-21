# Tailwind CSS Knowledge Pack

## CRITICAL: Tailwind v3 vs v4 (Setup Differs)

v3.x (most common right now):

    npm install -D tailwindcss postcss autoprefixer
    npx tailwindcss init -p

v4 (new, simpler):

    npm install tailwindcss @tailwindcss/vite

## CRITICAL: tailwind.config.js (v3)

    export default {
      content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx,vue}",
      ],
      theme: {
        extend: {},
      },
      plugins: [],
    }

The content array is CRITICAL. Without it, Tailwind purges everything.
Always include ./index.html AND all source file globs.

## CRITICAL: postcss.config.js

    export default {
      plugins: {
        tailwindcss: {},
        autoprefixer: {},
      },
    }

## CRITICAL: src/index.css (Entry)

    @tailwind base;
    @tailwind components;
    @tailwind utilities;

Then import in src/main.jsx (React) or src/main.js (Vue):

    import './index.css'

## v4 Setup (Simpler - Vite Plugin)

    // vite.config.js
    import tailwindcss from '@tailwindcss/vite'

    export default {
      plugins: [react(), tailwindcss()]
    }

    /* src/index.css */
    @import "tailwindcss";

No config file needed for basic use.

## Common Patterns

Container with responsive padding:
    <div class="container mx-auto px-4 sm:px-6 lg:px-8">

Flexbox center:
    <div class="flex items-center justify-center min-h-screen">

Grid responsive:
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">

Card:
    <div class="bg-white rounded-lg shadow-md p-6 hover:shadow-lg transition">

Button:
    <button class="bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg">

Dark mode:
    <body class="bg-white dark:bg-gray-900 text-gray-900 dark:text-white">

## Common Errors

| Symptom | Cause | Fix |
|---|---|---|
| Classes don't apply | Missing entry in content | Add all source globs to tailwind.config.js |
| Nothing styled | Forgot @tailwind directives | Add to src/index.css |
| @tailwind unknown | PostCSS not configured | Create postcss.config.js |
| Custom colors not working | Theme.extend.colors needed | Use extend, not colors |
| bg-primary-500 not found | Custom color not defined | Add to theme.extend.colors |

## Dark Mode Setup

    // tailwind.config.js
    export default {
      darkMode: 'class',
    }

    <html class="dark">

## Recommended UI Component Libraries

- shadcn/ui - Copy-paste React components built on Tailwind + Radix
- DaisyUI - Plugin that adds pre-styled components
- HeadlessUI - Unstyled accessible primitives
- Flowbite - Pre-built component library
