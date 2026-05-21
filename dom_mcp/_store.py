"""
Thread-safe DOM snapshot store.
Single responsibility: hold per-tab frame state and merge top-frame + iframes on read.

Storage model:
  _top_frames: {tabId → snapshot}   — most recent visible top-level frame per tab
  _iframes:    {tabId → [snapshot]} — all iframe snapshots for that tab
  _active_tab: most recently updated tabId

When a new top-frame URL is seen for a tab, its iframe list is cleared (page navigation).
"""
from __future__ import annotations
import threading
from typing import Optional


class DomStore:
    def __init__(self) -> None:
        self._top_frames: dict[int, dict] = {}
        self._iframes: dict[int, list[dict]] = {}
        self._active_tab: int = -1
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def update(self, data: dict) -> None:
        tab_id = int(data.get("tabId", -1))
        is_top = data.get("isTopFrame", True)

        with self._cond:
            if is_top:
                prev = self._top_frames.get(tab_id, {})
                if prev.get("url") != data.get("url"):
                    self._iframes[tab_id] = []          # navigated — clear stale iframes
                self._top_frames[tab_id] = data
                self._active_tab = tab_id
            else:
                frame_url = data.get("frameUrl", "")
                frames = self._iframes.get(tab_id, [])
                frames = [f for f in frames if f.get("frameUrl") != frame_url]
                frames.append(data)
                self._iframes[tab_id] = frames

            self._cond.notify_all()

    def get(self, tab_id: Optional[int] = None) -> dict:
        with self._lock:
            tid = tab_id if tab_id is not None else self._active_tab
            top = self._top_frames.get(tid, {})
            if not top:
                return {}
            result = dict(top)
            frames = self._iframes.get(tid, [])
            if frames:
                result["iframes"] = [
                    {
                        "url":          f.get("frameUrl"),
                        "questions":    f.get("questions", []),
                        "radio_groups": f.get("radio_groups", []),
                        "inputs":       f.get("inputs", []),
                        "passage":      f.get("passage", []),
                    }
                    for f in frames
                ]
            return result

    def wait_for_update(self, timeout: float) -> dict:
        with self._cond:
            self._cond.wait(timeout=timeout)
            return self.get()

    def active_tabs(self) -> list[dict]:
        with self._lock:
            return [
                {"tabId": tid, "url": snap.get("url"), "title": snap.get("title")}
                for tid, snap in self._top_frames.items()
            ]
