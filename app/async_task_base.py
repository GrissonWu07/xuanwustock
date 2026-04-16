from __future__ import annotations

import threading
from typing import Any, Callable
from uuid import uuid4

from app.i18n import t


class AsyncTaskManagerBase:
    def __init__(self, *, task_prefix: str, title: str, limit: int = 200) -> None:
        self.task_prefix = task_prefix.strip() or "task"
        self.task_title = title.strip() or t("Async task")
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._limit = max(limit, 20)

    def owns_task(self, task_id: str) -> bool:
        return str(task_id).startswith(f"{self.task_prefix}-")

    def create_task(
        self,
        *,
        now: Callable[[], str],
        message: str | None = None,
        stage: str = "queued",
        progress: int = 0,
        symbol: str = "",
        **fields: Any,
    ) -> str:
        task_id = f"{self.task_prefix}-{uuid4().hex[:10]}"
        created = now()
        payload = {
            "id": task_id,
            "status": "queued",
            "title": self.task_title,
            "message": str(message or t("Task submitted")),
            "stage": stage,
            "progress": max(0, min(int(progress), 100)),
            "symbol": symbol,
            "created_at": created,
            "started_at": None,
            "finished_at": None,
            "updated_at": created,
            **fields,
        }
        with self._lock:
            self._tasks[task_id] = payload
            self._order.append(task_id)
            while len(self._order) > self._limit:
                dropped = self._order.pop(0)
                self._tasks.pop(dropped, None)
        return task_id

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def latest_task(self) -> dict[str, Any] | None:
        with self._lock:
            for task_id in reversed(self._order):
                task = self._tasks.get(task_id)
                if task and task.get("status") in {"queued", "running"}:
                    return dict(task)
            for task_id in reversed(self._order):
                task = self._tasks.get(task_id)
                if task:
                    return dict(task)
        return None

    def update_task(self, task_id: str, *, now: Callable[[], str], **updates: Any) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.update(updates)
            task["updated_at"] = now()
            return dict(task)

    def start_background(
        self,
        *,
        task_id: str,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        name_prefix: str | None = None,
    ) -> threading.Thread:
        thread = threading.Thread(
            target=target,
            args=args,
            kwargs=kwargs or {},
            name=f"{name_prefix or self.task_prefix}-{task_id}",
            daemon=True,
        )
        thread.start()
        return thread

    def job_view(
        self,
        task: dict[str, Any] | None,
        *,
        txt: Callable[[Any, str], str],
        int_fn: Callable[[Any, int | None], int | None],
    ) -> dict[str, Any] | None:
        if not task:
            return None
        return {
            "id": txt(task.get("id"), ""),
            "status": txt(task.get("status"), "idle"),
            "title": txt(task.get("title"), self.task_title),
            "message": txt(task.get("message"), t("Task submitted")),
            "stage": txt(task.get("stage"), ""),
            "progress": int_fn(task.get("progress"), 0) or 0,
            "symbol": txt(task.get("symbol"), ""),
            "startedAt": txt(task.get("started_at"), ""),
            "updatedAt": txt(task.get("updated_at"), ""),
        }

    def task_response(
        self,
        task: dict[str, Any],
        *,
        txt: Callable[[Any, str], str],
        int_fn: Callable[[Any, int | None], int | None],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": txt(task.get("id"), ""),
            "status": txt(task.get("status"), "idle"),
            "title": txt(task.get("title"), self.task_title),
            "message": txt(task.get("message"), ""),
            "stage": txt(task.get("stage"), ""),
            "progress": int_fn(task.get("progress"), 0) or 0,
            "symbol": txt(task.get("symbol"), ""),
            "taskType": self.task_prefix,
            "startedAt": txt(task.get("started_at"), ""),
            "updatedAt": txt(task.get("updated_at"), ""),
            "finishedAt": txt(task.get("finished_at"), ""),
        }
        if isinstance(task.get("codes"), list):
            payload["stockCodes"] = task.get("codes")
        if "mode" in task:
            payload["mode"] = txt(task.get("mode"), "")
        if "cycle" in task:
            payload["cycle"] = txt(task.get("cycle"), "")
        if isinstance(task.get("results"), list):
            payload["resultCount"] = len(task.get("results") or [])
            payload["results"] = task.get("results")
        if isinstance(task.get("errors"), list):
            payload["errors"] = task.get("errors")
        if "result" in task:
            payload["result"] = task.get("result")
        if isinstance(task.get("payload"), dict):
            payload["payload"] = task.get("payload")
        return payload


__all__ = ["AsyncTaskManagerBase"]
