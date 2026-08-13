from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import List, Optional, Tuple

from models import Task, TaskStatus, TaskStore


def export_tasks(path: Path, fmt: str, store: TaskStore) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt == "json":
        path.write_text(
            json.dumps(store.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    elif fmt == "txt":
        lines = [t.title for t in store.tasks]
        path.write_text("\n".join(lines), encoding="utf-8")
    elif fmt == "csv":
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Название", "Статус"])
            for t in store.tasks:
                writer.writerow([t.title, t.status.value])


def _clean_title(title: str) -> Optional[str]:
    title = title.strip()
    if not title:
        return None
    if len(title) > TaskStore.MAX_TITLE:
        title = title[: TaskStore.MAX_TITLE]
    return title


def load_tasks(path: Path, fmt: str) -> List[Tuple[str, Optional[TaskStatus]]]:
    """Возвращает список (title, status) из файла. TXT не содержит статусов."""
    path = Path(path)
    fmt = fmt.lower()
    result: List[Tuple[str, Optional[TaskStatus]]] = []

    if fmt == "txt":
        for line in path.read_text(encoding="utf-8").splitlines():
            title = _clean_title(line)
            if title is not None:
                result.append((title, None))
    elif fmt == "csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i == 0 and row and row[0].strip().lower() == "название":
                    continue
                if not row or not row[0].strip():
                    continue
                title = _clean_title(row[0])
                if title is None:
                    continue
                status = TaskStatus.TO_DO
                if len(row) > 1 and row[1].strip():
                    try:
                        status = TaskStatus(row[1].strip())
                    except ValueError:
                        status = TaskStatus.TO_DO
                result.append((title, status))
    elif fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        tasks = data.get("tasks", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        if isinstance(tasks, list):
            for item in tasks:
                if not isinstance(item, dict):
                    continue
                title = _clean_title(str(item.get("title", "")))
                if title is None:
                    continue
                status = TaskStatus.TO_DO
                try:
                    status = TaskStatus(str(item.get("status", TaskStatus.TO_DO.value)))
                except ValueError:
                    status = TaskStatus.TO_DO
                result.append((title, status))
    return result


def apply_import(store: TaskStore, items: List[Tuple[str, Optional[TaskStatus]]], mode: str) -> int:
    """Применяет импорт. mode: 'replace' или 'add'. Возвращает число добавленных задач."""
    if mode == "replace":
        store.tasks = []
    added = 0
    for title, status in items:
        if len(store.tasks) >= TaskStore.MAX_TASKS:
            break
        task = Task.create(title)
        if status is not None:
            task.status = status
        store.tasks.append(task)
        added += 1
    store.rebuild_orders()
    return added