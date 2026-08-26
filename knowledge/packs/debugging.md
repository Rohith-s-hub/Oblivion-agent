# ELITE DEBUGGING & ERROR RESOLUTION KNOWLEDGE

When presented with compiler, runtime, or import errors, you must act as a Senior Staff Engineer diagnosing a broken build.

## React & Vite "Failed to resolve import" Errors
**Root Cause:** The file `src/App.tsx` is trying to import a component (e.g., `./pages/About`), but the file `src/pages/About.tsx` or `src/pages/About.jsx` does not exist on disk.

**Resolution Steps:**
1. Call `project_map` to verify the existence of the `src/pages/` or `src/components/` directories.
2. If the directory is missing, call `create_dir`.
3. If the file is missing, use `batch_edit` to create the missing file with boilerplate code (e.g. `export default function About() { return <div>About</div>; }`).
4. Ensure the file extension matches the project type (use `.tsx` for TypeScript, `.jsx` for JavaScript).

## General Bug Fixing Mindset
- **Read the Code First:** Never attempt a fix without running `read_file` on the exact file mentioned in the stack trace.
- **Check Surrounding Context:** Import errors are often caused by typos in folder names (e.g. `Component` vs `components`). Run `list_dir` on the parent folder to verify exact casing.
- **Do Not Re-architect:** If a user pastes a single missing import error, just create the missing file or fix the import line. Do not rewrite their entire application or create new workspaces.
