from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import List


class TaskStatus(Enum):
    TO_DO = "To Do"
    STARTED = "Started"
    DONE = "Done"

    @property
    def is_active(self) -> bool:
        return self is not TaskStatus.DONE

    @property
    def color(self) -> str:
        return STATUS_DEFAULT_COLORS[self]


def next_status(status: TaskStatus) -> TaskStatus:
    order = [TaskStatus.TO_DO, TaskStatus.STARTED, TaskStatus.DONE]
    return order[(order.index(status) + 1) % len(order)]


def prev_status(status: TaskStatus) -> TaskStatus:
    order = [TaskStatus.TO_DO, TaskStatus.STARTED, TaskStatus.DONE]
    return order[(order.index(status) - 1) % len(order)]


STATUS_DEFAULT_COLORS = {
    TaskStatus.TO_DO: "#5B7BD5",
    TaskStatus.STARTED: "#E0913C",
    TaskStatus.DONE: "#4CAF50",
}


def status_color(status: TaskStatus, settings=None) -> str:
    """Цвет статуса: пользовательская настройка или значение по умолчанию."""
    if settings is not None:
        key = {
            TaskStatus.TO_DO: "color_status_todo",
            TaskStatus.STARTED: "color_status_started",
            TaskStatus.DONE: "color_status_done",
        }[status]
        value = getattr(settings, key, "") or ""
        if value.strip():
            return value.strip()
    return STATUS_DEFAULT_COLORS[status]


@dataclass
class Task:
    id: str
    title: str
    status: TaskStatus
    position: int = 0
    regular: bool = False
    urgent: bool = False

    @classmethod
    def create(cls, title: str) -> "Task":
        return cls(id=uuid.uuid4().hex, title=title, status=TaskStatus.TO_DO, position=0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "position": self.position,
            "regular": self.regular,
            "urgent": self.urgent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        status = data.get("status", TaskStatus.TO_DO.value)
        st = TaskStatus.TO_DO
        if isinstance(status, str):
            try:
                st = TaskStatus(status)
            except ValueError:
                st = TaskStatus.TO_DO
        elif isinstance(status, int):
            all_statuses = list(TaskStatus)
            if 0 <= status < len(all_statuses):
                st = all_statuses[status]
        try:
            pos = int(data.get("position", 0))
        except (TypeError, ValueError):
            pos = 0
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            title=str(data.get("title", "")),
            status=st,
            position=pos,
            regular=bool(data.get("regular", False)),
            urgent=bool(data.get("urgent", False)),
        )


class TaskLimitError(Exception):
    pass


class TaskStore:
    MAX_TASKS = 100
    MAX_TITLE = 255

    def __init__(self) -> None:
        self.tasks: List[Task] = []

    def __len__(self) -> int:
        return len(self.tasks)

    def _first_done_index(self) -> int:
        for i, t in enumerate(self.tasks):
            if t.status is TaskStatus.DONE:
                return i
        return len(self.tasks)

    def first_done_index(self) -> int:
        return self._first_done_index()

    def add(self, title: str) -> Task:
        title = title.strip()
        if not title:
            raise ValueError("Название не может быть пустым")
        if len(title) > self.MAX_TITLE:
            title = title[: self.MAX_TITLE]
        if len(self.tasks) >= self.MAX_TASKS:
            raise TaskLimitError("Достигнуто максимальное количество задач: 100")
        task = Task.create(title)
        # Новая задача вставляется после всех срочных активных (они всегда наверху)
        insert_at = sum(1 for t in self.tasks if t.urgent and t.status.is_active)
        self.tasks.insert(insert_at, task)
        self.rebuild_orders()
        return task

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.tasks):
            del self.tasks[index]
            self.rebuild_orders()

    def rename(self, index: int, title: str) -> str:
        title = title.strip()
        if not title:
            raise ValueError("Название не может быть пустым")
        if len(title) > self.MAX_TITLE:
            title = title[: self.MAX_TITLE]
        self.tasks[index].title = title
        return title

    def set_status(self, index: int, new_status: TaskStatus) -> None:
        if not (0 <= index < len(self.tasks)):
            return
        task = self.tasks[index]
        if task.status is new_status:
            return
        old_status = task.status
        task.status = new_status
        if old_status is TaskStatus.DONE:
            # выход из Done -> после срочных активных (они всегда наверху), перед остальными активными
            self.tasks.pop(index)
            urgent_active = sum(1 for t in self.tasks if t.urgent and t.status.is_active)
            self.tasks.insert(urgent_active, task)
        elif new_status is TaskStatus.DONE:
            # переход в Done -> в конец списка (блок Done)
            self.tasks.pop(index)
            self.tasks.append(task)
        else:
            # To Do -> Started: задача остаётся на своём месте
            pass
        self.rebuild_orders()

    def move_to_slot(self, from_index: int, to_slot: int) -> None:
        if not (0 <= from_index < len(self.tasks)):
            return
        if self.tasks[from_index].urgent:
            return  # срочные задачи не перемещаются
        task = self.tasks.pop(from_index)
        n = len(self.tasks)
        to_slot = max(0, min(to_slot, n))
        if task.status.is_active:
            done = self._first_done_index()
            to_slot = max(0, min(to_slot, done))
        self.tasks.insert(to_slot, task)
        self.rebuild_orders()

    def rebuild_orders(self) -> None:
        for i, t in enumerate(self.tasks):
            t.position = i

    def to_dict(self) -> dict:
        return {"tasks": [t.to_dict() for t in self.tasks]}

    def load_dict(self, data) -> None:
        if not isinstance(data, dict):
            data = {}
        raw = data.get("tasks", [])
        tasks: List[Task] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    try:
                        tasks.append(Task.from_dict(item))
                    except Exception:
                        pass
        tasks.sort(key=lambda t: t.position)
        self.tasks = tasks[: self.MAX_TASKS]
        self.rebuild_orders()

    def active_tasks(self) -> List[Task]:
        return [t for t in self.tasks if t.status.is_active]

    def regular_tasks(self) -> List[Task]:
        return [t for t in self.tasks if t.regular]

    def set_regular(self, index: int, value: bool) -> None:
        if 0 <= index < len(self.tasks):
            self.tasks[index].regular = value

    def set_urgent(self, index: int, value: bool) -> None:
        if not (0 <= index < len(self.tasks)):
            return
        task = self.tasks[index]
        if task.urgent == value:
            return
        task.urgent = value
        # Срочные активные задачи закрепляются вверху списка, сохраняя порядок
        # их назначения (ранее назначенные — выше). Остальные — ниже. Done — в конце.
        urgent_active = [t for t in self.tasks if t.urgent and t.status.is_active]
        other_active = [t for t in self.tasks if not t.urgent and t.status.is_active]
        done = [t for t in self.tasks if t.status is TaskStatus.DONE]
        self.tasks = urgent_active + other_active + done
        self.rebuild_orders()

    def reset_regular_to_todo(self) -> bool:
        """Сбрасывает статус регулярных задач на To Do и поднимает их в самый верх списка."""
        reset_tasks = []
        for t in self.tasks:
            if t.regular and t.status is not TaskStatus.TO_DO:
                t.status = TaskStatus.TO_DO
                reset_tasks.append(t)
        if not reset_tasks:
            return False
        reset_ids = {t.id for t in reset_tasks}
        rest = [t for t in self.tasks if t.id not in reset_ids]
        self.tasks = reset_tasks + rest
        self.rebuild_orders()
        return True

    def tasks_by_status(self, status: TaskStatus) -> List[Task]:
        return [t for t in self.tasks if t.status is status]