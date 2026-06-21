# Vue 3 Knowledge Pack

## CRITICAL: Modern Vue (3.4+) Uses Composition API

- Vue 3 with <script setup> is the standard
- Vite is the official build tool (NOT Vue CLI / webpack)
- Default port: 5173

## Project Setup

    npm create vue@latest my-app
    npm install && npm run dev

## CRITICAL: vite.config.js

    import { defineConfig } from 'vite'
    import vue from '@vitejs/plugin-vue'

    export default defineConfig({
      plugins: [vue()],
      server: {
        port: 3000,
        host: true
      }
    })

## CRITICAL: package.json

    {
      "type": "module",
      "scripts": {
        "dev": "vite",
        "build": "vite build",
        "preview": "vite preview"
      },
      "dependencies": {
        "vue": "^3.4.0"
      },
      "devDependencies": {
        "@vitejs/plugin-vue": "^5.0.0",
        "vite": "^5.0.0"
      }
    }

## CRITICAL: src/main.js

    import { createApp } from 'vue'
    import App from './App.vue'
    import './style.css'

    createApp(App).mount('#app')

## CRITICAL: src/App.vue (Composition API)

    <script setup>
    import { ref, computed } from 'vue'

    const count = ref(0)
    const doubled = computed(() => count.value * 2)
    </script>

    <template>
      <h1>Count: {{ count }}</h1>
      <p>Doubled: {{ doubled }}</p>
      <button @click="count++">+</button>
    </template>

    <style scoped>
    button { padding: 0.5rem 1rem; }
    </style>

## Folder Layout

    my-app/
    ├── index.html
    ├── vite.config.js
    ├── package.json
    └── src/
        ├── main.js
        ├── App.vue
        ├── style.css
        ├── components/
        ├── views/
        ├── router/
        ├── stores/
        └── assets/

## Routing (vue-router 4)

    npm install vue-router@4

    // src/router/index.js
    import { createRouter, createWebHistory } from 'vue-router'
    import Home from '../views/Home.vue'

    export default createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', component: Home },
        { path: '/about', component: () => import('../views/About.vue') }
      ]
    })

## State (Pinia, the official store)

    npm install pinia

    // src/stores/counter.js
    import { defineStore } from 'pinia'

    export const useCounterStore = defineStore('counter', {
      state: () => ({ count: 0 }),
      actions: { increment() { this.count++ } }
    })

## Common Errors

| Error | Fix |
|---|---|
| Failed to resolve component | Component not imported or registered |
| Cannot read .value of undefined | Forgot .value on a ref() outside template |
| Hydration mismatch (Nuxt) | Don't use window / document in setup without onMounted |
| Blank page | Check browser console; npm run dev shows compile errors |
