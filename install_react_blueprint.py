import os
import re
import ast
from pathlib import Path

base_dir = Path(".").resolve()

# 1. UPDATE AGENT/CORE.PY
core_path = base_dir / "agent" / "core.py"
c_core = core_path.read_text(encoding="utf-8")

react_blueprint = """
## STRICT REACT & VITE ARCHITECTURAL BLUEPRINT

When creating or editing React applications (Vite / React Router / Tailwind):

### Standard Folder Structure (ALWAYS USE THIS EXACT PATTERN):
project-root/
├── index.html          # Entry HTML with <div id="root"></div> and <script type="module" src="/src/main.jsx"></script>
├── package.json        # Dependencies: react, react-dom, react-router-dom, lucide-react
├── vite.config.js      # Vite React plugin config
├── src/
│   ├── main.jsx        # ReactDOM.createRoot rendering <App /> wrapped in <BrowserRouter>
│   ├── App.jsx         # Main router shell with <Navbar />, <Routes>, <Footer />
│   ├── index.css       # Tailwind / Global CSS variables
│   ├── components/     # Reusable UI components (Navbar.jsx, Footer.jsx, Card.jsx)
│   ├── pages/          # Page views matching routes (Home.jsx, About.jsx, Products.jsx, Contact.jsx)
│   └── data/           # Mock data stores (mockData.js)

### React Execution Rules:
1. Never mix .jsx and .tsx extensions in the same project. Use .jsx for JS or .tsx for TS consistently.
2. Always wrap routes in BrowserRouter inside main.jsx:
   import React from 'react';
   import ReactDOM from 'react-dom/client';
   import { BrowserRouter } from 'react-router-dom';
   import App from './App';
   import './index.css';

   ReactDOM.createRoot(document.getElementById('root')).render(
     <React.StrictMode>
       <BrowserRouter>
         <App />
       </BrowserRouter>
     </React.StrictMode>
   );
3. Atomic Batching (MAX 3 BATCHES FOR FULL SITE):
   - Batch 1 (Scaffold): package.json, vite.config.js, index.html, src/index.css, src/main.jsx
   - Batch 2 (Core Shell): src/App.jsx, src/components/Navbar.jsx, src/components/Footer.jsx, src/data/mockData.js
   - Batch 3 (All Pages): src/pages/Home.jsx, src/pages/About.jsx, src/pages/Products.jsx, src/pages/Contact.jsx
4. Fixing React Import Errors: When an error says "Failed to resolve import ./pages/X from src/App.jsx":
   - Read src/App.jsx first using read_file.
   - Check if src/pages/X.jsx exists on disk. If missing, create src/pages/X.jsx immediately using batch_edit.
"""

if "STRICT REACT & VITE ARCHITECTURAL BLUEPRINT" not in c_core:
    target_marker = "## RULES (obey all — this is the entire discipline)"
    if target_marker in c_core:
        c_core = c_core.replace(target_marker, react_blueprint + "\n\n" + target_marker)
        core_path.write_text(c_core, encoding="utf-8")
        print("✅ 1. Installed React Architecture Blueprint in agent/core.py")

ast.parse(core_path.read_text(encoding="utf-8"))

# 2. UPDATE KNOWLEDGE/PACKS/REACT.MD
react_pack_path = base_dir / "knowledge" / "packs" / "react.md"
react_pack_content = """# REACT & VITE PRODUCTION PATTERNS

## Component & Page Routing Architecture

When building or editing React applications with React Router v6:

### 1. Entry Point (src/main.jsx)
```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
2. Router Shell (src/App.jsx)
React

import { Routes, Route } from 'react-router-dom'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import Home from './pages/Home'
import About from './pages/About'
import Products from './pages/Products'
import Contact from './pages/Contact'

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <Navbar />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/about" element={<About />} />
          <Route path="/products" element={<Products />} />
          <Route path="/contact" element={<Contact />} />
        </Routes>
      </main>
      <Footer />
    </div>
  )
}
3. Common Error Fixes
Import Resolution Error: Check relative path slashes (e.g. ./components/Navbar vs ../components/Navbar).
Missing Default Export: Ensure every page component has export default function ComponentName() { ... }.
Vite Host Binding: Set server: { host: true, port: 3000 } in vite.config.js so preview works across ports.
"""
react_pack_path.parent.mkdir(parents=True, exist_ok=True)
react_pack_path.write_text(react_pack_content, encoding="utf-8")
print("✅ 2. Updated knowledge/packs/react.md with Vite/React Router patterns")

3. UPDATE AGENT/RUNTIME.PY & CONFIG.ENV
rt_path = base_dir / "agent" / "runtime.py"
c_rt = rt_path.read_text(encoding="utf-8")

c_rt = re.sub(r'max_iterations:\sint\s=\s*\d+', 'max_iterations: int = 40', c_rt)
rt_path.write_text(c_rt, encoding="utf-8")
print("✅ 3. Updated default MAX_ITERATIONS to 40 in agent/runtime.py")

cfg_path = Path.home() / ".oblivion" / "config.env"
if cfg_path.exists():
c_cfg = cfg_path.read_text(encoding="utf-8")
if "MAX_ITERATIONS=" in c_cfg:
c_cfg = re.sub(r"MAX_ITERATIONS=\d+", "MAX_ITERATIONS=40", c_cfg)
else:
c_cfg += "\nMAX_ITERATIONS=40\n"
cfg_path.write_text(c_cfg, encoding="utf-8")
print("✅ 4. Updated MAX_ITERATIONS=40 in ~/.oblivion/config.env")

SYNTAX CHECKS
ast.parse(core_path.read_text(encoding="utf-8"))
ast.parse(rt_path.read_text(encoding="utf-8"))
print("\n🎉 ALL REACT ARCHITECTURE & STEP BUDGET FIXES INSTALLED SUCCESSFULLY!")
