"""
Background file watcher.
Detects file save/create/delete events in workspace and triggers incremental re-index.
"""
import time
import asyncio
import threading
from pathlib import Path
from typing import Callable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

from agent.rag import index_single_file, should_index, WORKSPACE


class CodeChangeHandler(FileSystemEventHandler):
    """Handle file system events and queue them for indexing."""

    def __init__(self, workspace: Path, on_change: Optional[Callable] = None):
        super().__init__()
        self.workspace = workspace
        self.on_change = on_change or (lambda evt: None)
        # Debounce: track recently-changed files to avoid double-processing
        self._recent: dict[str, float] = {}
        self._debounce_seconds = 1.5

    def _should_process(self, path_str: str) -> bool:
        """Debounce - ignore if same file processed within last 1.5s."""
        now = time.time()
        last = self._recent.get(path_str, 0)
        if now - last < self._debounce_seconds:
            return False
        self._recent[path_str] = now
        # Clean old entries
        cutoff = now - 10
        self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
        return True

    def _handle(self, event_type: str, src: str):
        path = Path(src)
        # Quick filter
        if not path.exists() and event_type != "deleted":
            return
        if path.is_dir():
            return
        # Use should_index for proper filtering (handles all skip rules)
        try:
            if event_type != "deleted" and not should_index(path):
                return
        except Exception:
            return
        if not self._should_process(src):
            return

        # Run indexing in a separate thread to not block watchdog
        threading.Thread(
            target=self._index_in_thread,
            args=(path, event_type),
            daemon=True,
        ).start()

    def _index_in_thread(self, path: Path, event_type: str):
        try:
            result = index_single_file(path, self.workspace)
            rel = str(path.relative_to(self.workspace)) if path.exists() else str(path)
            self.on_change({
                "type": event_type,
                "file": rel,
                "status": result["status"],
                "chunks_added": result["chunks_added"],
                "deleted": result["deleted"],
            })
        except Exception as e:
            self.on_change({"type": "error", "file": str(path), "error": str(e)})

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle("modified", event.src_path)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle("created", event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            self._handle("deleted", event.src_path)


class FileWatcher:
    """
    Watches a workspace for changes and auto-indexes.
    
    Usage:
        watcher = FileWatcher(callback=lambda evt: print(evt))
        watcher.start()
        # ... do stuff ...
        watcher.stop()
    """

    def __init__(self, workspace: Path = None, callback: Optional[Callable] = None):
        self.workspace = workspace or WORKSPACE
        self.callback = callback
        self.observer: Optional[Observer] = None

    def start(self):
        if self.observer is not None:
            return  # already running
        handler = CodeChangeHandler(self.workspace, self.callback)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.workspace), recursive=True)
        self.observer.start()

    def stop(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer.join(timeout=2)
            self.observer = None

    def is_running(self) -> bool:
        return self.observer is not None and self.observer.is_alive()
