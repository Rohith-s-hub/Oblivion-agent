import os, ast, re
from pathlib import Path

BASE = Path.home() / "ai-agent"

# ── 1. REWRITE KNOWLEDGE/PACKS/WEBDEV.MD ──────────────────────────────────────
webdev_path = BASE / "knowledge" / "packs" / "webdev.md"

vibrant_webdev_content = """# VIBRANT ELITE WEB DESIGN SYSTEM

## 🎨 MANDATORY VIBRANT DESIGN SYSTEM (DARK MODE & GRADIENTS)

When generating ANY website, you MUST write a rich, complete CSS file (minimum 1,500+ characters) containing design tokens, glassmorphism, animations, and component styles. NEVER write a barebones or short CSS file!

### 1. Color System (Vibrant & Glowing)
- **Backgrounds:** Deep slate/midnight (`#0a0a12`, `#0f172a`, `#111827`). NEVER use plain white backgrounds.
- **Cards/Surfaces:** Glassmorphic containers (`rgba(255, 255, 255, 0.04)`) with `1px solid rgba(255, 255, 255, 0.1)` borders.
- **Accents:** Neon Indigo (`#6366f1`), Cyan (`#22d3ee`), Violet (`#8b5cf6`), and Rose (`#f43f5e`).
- **Text:** Crisp white (`#f8fafc`) for headings, soft gray (`#94a3b8`) for body.

### 2. Mandatory CSS Starter (Inject into `styles.css` / `style.css`)

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  --bg-dark: #0a0a12;
  --bg-card: rgba(255, 255, 255, 0.04);
  --bg-card-hover: rgba(255, 255, 255, 0.08);
  --text-main: #f8fafc;
  --text-muted: #94a3b8;
  --accent-primary: #8b5cf6;
  --accent-secondary: #22d3ee;
  --accent-gradient: linear-gradient(135deg, #8b5cf6 0%, #22d3ee 100%);
  --border-subtle: rgba(255, 255, 255, 0.1);
  --border-glow: rgba(139, 92, 246, 0.4);
  --glow-shadow: 0 10px 30px -10px rgba(139, 92, 246, 0.4);
  --radius-lg: 16px;
  --radius-pill: 9999px;
  --transition-smooth: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; }

body {
  background-color: var(--bg-dark);
  color: var(--text-main);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}

.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

/* Gradient Headlines */
.gradient-text {
  background: var(--accent-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* Glassmorphism Navbar */
.navbar {
  position: sticky;
  top: 0;
  z-index: 1000;
  background: rgba(10, 10, 18, 0.8);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border-subtle);
  padding: 16px 0;
}

/* Vibrant Buttons */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 12px 28px;
  border-radius: var(--radius-pill);
  font-weight: 600;
  font-size: 0.95rem;
  text-decoration: none;
  transition: var(--transition-smooth);
  cursor: pointer;
  border: none;
}

.btn-primary {
  background: var(--accent-gradient);
  color: #ffffff;
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);
}

.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: var(--glow-shadow);
  filter: brightness(1.1);
}

/* Interactive Glowing Cards */
.card {
  background: var(--bg-card);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  padding: 28px;
  transition: var(--transition-smooth);
}

.card:hover {
  transform: translateY(-6px);
  background: var(--bg-card-hover);
  border-color: var(--border-glow);
  box-shadow: var(--glow-shadow);
}
🚀 EXECUTION & COMPLETION RULES
FULL CSS REQUIRED: styles.css / style.css MUST contain the complete design token system above. Never write a short 200-byte CSS file!
PRIORITIZE CORE SUB-PAGES: Always generate index.html, about.html, contact.html, and styles.css in your VERY FIRST batch call before generating individual article/blog pages.
NO PLACEHOLDERS: All pages must be fully styled, responsive, and populated with real copy.
"""
webdev_path.parent.mkdir(parents=True, exist_ok=True)
webdev_path.write_text(vibrant_webdev_content, encoding="utf-8")
print("✅ 1. knowledge/packs/webdev.md updated with Vibrant Design System!")

── 2. UPDATE AGENT/CORE.PY TO ENFORCE VIBRANT STYLING ─────────────────────
path_core = BASE / "agent" / "core.py"
content_core = path_core.read_text(encoding="utf-8")

old_rule = "2. WEBSITE & MULTI-FILE GENERATION (CHUNKED BATCH EXECUTION):"

new_rule = """2. WEBSITE GENERATION (VIBRANT STYLING & FULL COMPLETION):

VIBRANT DESIGN: Always write a comprehensive styles.css (minimum 1,500+ characters) using dark slate backgrounds (#0a0a12), cyan/violet gradients, glassmorphism navbars, and glowing hover cards as specified in webdev.md.
PRIORITIZE SUB-PAGES: Generate index.html, about.html, contact.html, and styles.css FIRST before individual blog/project detail pages.
Use batch_edit to write files in complete chunks so no pages are left missing."""
if old_rule in content_core:
content_core = re.sub(
r'2. **WEBSITE & MULTI-FILE GENERATION.*?(?=\n\n3.)',
new_rule,
content_core,
flags=re.DOTALL
)
path_core.write_text(content_core, encoding="utf-8")
print("✅ 2. agent/core.py updated to enforce Vibrant CSS & Sub-Page Completion!")

Syntax Check
ast.parse(open(path_core).read())
print("✅ agent/core.py syntax PASSED!")
