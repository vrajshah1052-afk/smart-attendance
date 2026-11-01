"""Orchestrated saga for cross-database consistency (MySQL <-> MongoDB).

There is no distributed transaction between MySQL and MongoDB, so each
business operation is a sequence of local transactions. If step N fails,
the compensations of steps N-1..1 run in reverse order. The state of every
saga is persisted in MySQL (saga_log) so a crash can be recovered later.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

StepFn = Callable[[dict[str, Any]], Any]


class SagaRecorder(Protocol):
    def start(self, saga_id: str, saga_type: str, subject: str, steps: list[str], created_by: int | None) -> None: ...
    def step(self, saga_id: str, step: str, status: str) -> None: ...
    def status(self, saga_id: str, status: str, error: str | None = None) -> None: ...


class InMemoryRecorder:
    """Used by unit tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, ...]] = []
        self.final: dict[str, str] = {}

    def start(self, saga_id: str, saga_type: str, subject: str, steps: list[str], created_by: int | None) -> None:
        self.events.append(("start", saga_type, subject))

    def step(self, saga_id: str, step: str, status: str) -> None:
        self.events.append(("step", step, status))

    def status(self, saga_id: str, status: str, error: str | None = None) -> None:
        self.events.append(("status", status))
        self.final[saga_id] = status


@dataclass
class SagaStep:
    name: str
    action: StepFn
    compensate: StepFn | None = None
    pivot: bool = False  # after a pivot step the saga can only go forward (retry)


@dataclass(eq=False)
class SagaFailed(Exception):
    saga_id: str
    step: str
    cause: BaseException
    compensated: bool
    compensation_errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"saga {self.saga_id} failed at '{self.step}': {self.cause}"


class Saga:
    def __init__(self, saga_type: str, subject: str, steps: list[SagaStep], recorder: SagaRecorder,
                 created_by: int | None = None, saga_id: str | None = None) -> None:
        self.saga_type = saga_type
        self.subject = subject
        self.steps = steps
        self.recorder = recorder
        self.created_by = created_by
        self.saga_id = saga_id or str(uuid.uuid4())

    def run(self, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
        ctx = ctx if ctx is not None else {}
        ctx["saga_id"] = self.saga_id
        self.recorder.start(self.saga_id, self.saga_type, self.subject, [s.name for s in self.steps], self.created_by)
        completed: list[SagaStep] = []
        passed_pivot = False
        for step in self.steps:
            try:
                self.recorder.step(self.saga_id, step.name, "RUNNING")
                step.action(ctx)
                self.recorder.step(self.saga_id, step.name, "DONE")
                completed.append(step)
                passed_pivot = passed_pivot or step.pivot
            except Exception as exc:  # noqa: BLE001 - every failure triggers compensation
                logger.error("Saga %s (%s) step '%s' failed: %s", self.saga_id, self.saga_type, step.name, exc)
                self._safe(self.recorder.step, self.saga_id, step.name, "FAILED")
                if passed_pivot:
                    # forward recovery only: the recovery job retries the remaining idempotent steps
                    self._safe(self.recorder.status, self.saga_id, "FAILED", f"{step.name}: {exc}")
                    raise SagaFailed(self.saga_id, step.name, exc, compensated=False) from exc
                self._safe(self.recorder.status, self.saga_id, "COMPENSATING", f"{step.name}: {exc}")
                errors = self._compensate(completed, ctx)
                final = "COMPENSATED" if not errors else "FAILED"
                self._safe(self.recorder.status, self.saga_id, final, "; ".join(errors) or None)
                raise SagaFailed(self.saga_id, step.name, exc, compensated=not errors,
                                 compensation_errors=errors) from exc
        self.recorder.status(self.saga_id, "COMPLETED")
        return ctx

    def _compensate(self, completed: list[SagaStep], ctx: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for step in reversed(completed):
            if step.compensate is None:
                continue
            try:
                step.compensate(ctx)
                self._safe(self.recorder.step, self.saga_id, step.name, "COMPENSATED")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Compensation of '%s' failed", step.name)
                errors.append(f"{step.name}: {exc}")
                self._safe(self.recorder.step, self.saga_id, step.name, "COMPENSATION_FAILED")
        return errors

    @staticmethod
    def _safe(fn: Callable[..., Any], *args: Any) -> None:
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 - recording must never mask the real error
            logger.error("Saga recorder failed: %s", exc)
