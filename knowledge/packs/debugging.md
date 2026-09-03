# ELITE WEB DEBUGGING KNOWLEDGE

## 🔴 GOLDEN RULE: READ BEFORE YOU FIX

Before attempting ANY fix for a web error:
1. Call `project_map` to see the complete file structure
2. Call `read_file` on the file mentioned in the error (e.g., `src/App.tsx`, `index.html`, `main.js`)
3. Call `list_dir` on the relevant directories to verify which files actually exist
4. Check if any recently created files are empty (0 bytes) — this is the #1 cause of 404 and import errors

## 🚫 NEVER DO THESE WHEN DEBUGGING
- NEVER create a new workspace or switch directories
- NEVER rewrite the entire project from scratch
- NEVER write empty (0-byte) files via batch_edit — every file must have real content
- NEVER guess at file paths — always verify with list_dir or project_map first
- NEVER claim "fixed" without verifying the fix actually works

## 📋 COMMON WEB ERRORS & EXACT FIXES

### 1. "404 Not Found" when opening HTML pages
**Root Causes (check in this order):**
- The HTML file does not exist on disk → Create it with real content
- The file exists but is EMPTY (0 bytes) → Rewrite it with full HTML content
- The file path in the link/route does not match the actual filename (case-sensitive on Linux)
- For SPA (React/Vue): missing hash-based routing or incorrect base URL

**Diagnosis Steps:**
1. `list_dir("pages/")` or `list_dir("src/pages/")` to see what files actually exist
2. `read_file("index.html")` to check the navigation links and routing logic
3. If files exist but are 0 bytes, the batch_edit that created them was truncated — regenerate them with FULL content

**Fix:** Create or regenerate the missing/empty file with complete HTML content. Never edit routing before confirming the target file exists and has content.

### 2. "Failed to resolve import" (React/Vite/Webpack)
**Root Causes:**
- The imported file does not exist at the specified path
- File extension mismatch (.jsx vs .tsx vs .js)
- Directory name case mismatch (Components vs components)
- Missing export statement in the target file

**Diagnosis Steps:**
1. `read_file("src/App.tsx")` or whichever file has the import error
2. `list_dir("src/components/")` to check exact filenames and casing
3. Compare the import path against actual file locations

**Fix:** Either create the missing file OR fix the import path. Never restructure the entire project.

### 3. "Cannot read properties of undefined" (JavaScript Runtime)
**Root Causes:**
- Accessing a property on a variable that is null/undefined
- API response missing expected fields
- DOM element not found (querySelector returned null)
- Array/object destructuring on empty data

**Diagnosis Steps:**
1. `read_file` the JS file mentioned in the stack trace
2. Find the exact line number referenced in the error
3. Check if the variable is properly initialized before access

**Fix:** Add null checks, optional chaining (?.), or default values.

### 4. "Mixed Content" or CORS errors
**Root Causes:**
- Loading HTTP resources from an HTTPS page
- API calls to a different origin without CORS headers
- Missing Access-Control-Allow-Origin on the server

**Fix:** Use relative URLs, add CORS headers, or proxy API calls through the same origin.

### 5. CSS/Layout broken (elements overlapping, invisible, or unstyled)
**Root Causes:**
- CSS file not linked in HTML <head>
- CSS file exists but is empty (0 bytes)
- Wrong CSS selector (class name mismatch)
- z-index stacking context issues
- Missing viewport meta tag

**Diagnosis Steps:**
1. `read_file("index.html")` — check if <link rel="stylesheet" href="style.css"> exists in <head>
2. `read_file("style.css")` — verify it has actual CSS content (not empty)
3. Check class names in HTML match those in CSS

### 6. Navigation links not working (SPA or Multi-Page)
**Root Causes for Multi-Page sites (plain HTML):**
- Links point to files that don't exist
- Links use wrong relative paths
- Links use hash routing (#) but pages are separate HTML files

**Diagnosis Steps:**
1. `read_file("index.html")` — extract all href values from nav links
2. For each href, call `file_exists` to verify the target file exists
3. If file exists but is empty, regenerate it

**Diagnosis Steps for React/Vue SPA:**
1. Check router configuration (React Router, Vue Router)
2. Verify component files exist at import paths
3. Check if routes use exact matching

### 7. Blank page / White screen of death
**Root Causes:**
- JavaScript error preventing render (check console)
- Missing root element in HTML (no div#root or div#app)
- Bundle not loading (wrong script src path)
- CSS setting body/html to display:none or opacity:0

**Fix:** Read index.html, verify script tags point to correct bundle, verify root element exists.

## 🔧 DEBUGGING WORKFLOW (MANDATORY)

When a user reports ANY error, follow this exact sequence:

Step 1: MAP → `project_map` to understand full structure
Step 2: READ → `read_file` on the file mentioned in the error
Step 3: VERIFY → `list_dir` to check file existence and sizes
Step 4: DIAGNOSE → Match error pattern to the list above
Step 5: FIX → Apply the minimal, targeted fix (edit_file or batch_edit)
Step 6: VERIFY → `list_dir` again to confirm files exist and are non-empty
Step 7: REPORT → Tell user exactly what was wrong and what was fixed

## ⚠️ CRITICAL: EMPTY FILE DETECTION

If batch_edit or write_file creates a file with 0 bytes or less than 50 characters:
- This is a FAILED WRITE caused by token limit truncation
- The file MUST be regenerated immediately with full content
- NEVER claim success if any file is 0 bytes
- Always verify with list_dir after batch_edit to check file sizes
