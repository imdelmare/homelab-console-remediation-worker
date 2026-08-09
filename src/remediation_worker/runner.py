from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .gateway import GatewayError, LeasedGatewayProxy
from .protocol import Engine, Gateway, Job


class Runner:
    def __init__(
        self,
        gateway: Gateway,
        engine: Engine,
        poll_max_seconds: int = 30,
        runtime_dir: Path | None = None,
        lease_safety_seconds: float = 5.0,
        shutdown_grace_seconds: float = 15.0,
        now=datetime.now,
        sleep=asyncio.sleep,
    ) -> None:
        self.gateway, self.engine, self.poll_max_seconds = gateway, engine, poll_max_seconds
        self.stop_requested = False
        self._stop_event = asyncio.Event()
        self.runtime_dir = runtime_dir
        self.lease_safety_seconds = max(0.001, float(lease_safety_seconds))
        self.shutdown_grace_seconds = max(0.1, float(shutdown_grace_seconds))
        self._now, self._sleep = now, sleep

    def stop(self) -> None:
        self.stop_requested = True
        self._stop_event.set()

    async def run_forever(self) -> None:
        delay = 1
        while not self.stop_requested:
            try:
                response = await self.gateway.call("tasks_worker_next", {})
                if not isinstance(response, dict):
                    raise GatewayError("mcp_invalid_response")
                raw_job = response.get("job")
                if raw_job is None:
                    await self._poll_wait(min(self.poll_max_seconds, max(1, response.get("retry_after_seconds", delay))))
                    delay = min(self.poll_max_seconds, delay * 2)
                    continue
                delay = 1
                await self.run_job(Job.from_dict(raw_job))
            except (GatewayError, KeyError, TypeError, ValueError):
                await self._poll_wait(delay)
                delay = min(self.poll_max_seconds, delay * 2)

    async def _poll_wait(self, seconds: float) -> None:
        if self.stop_requested:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def run_job(self, job: Job) -> None:
        initial_expiry = self._expiry(job.lease_expires_at)
        proxy = LeasedGatewayProxy(self.gateway, job)
        lease_file = self._create_context(job)
        engine_task = asyncio.create_task(self.engine.run(job, lease_file))
        expiry = [initial_expiry]
        renew_task = asyncio.create_task(self._renew_loop(job, engine_task, expiry))
        lease_lost = False
        exit_code = 1
        try:
            while not engine_task.done():
                if renew_task.done():
                    lease_lost = self._renew_result(renew_task)
                if lease_lost:
                    await self.engine.terminate()
                    break
                if self.stop_requested:
                    await self.engine.terminate()
                    break
                await self._sleep(0.05)
            try:
                exit_code = await engine_task
            except asyncio.CancelledError:
                raise
            except Exception:
                # The engine output is deliberately unavailable; only normalize failure.
                exit_code = 1

            # Stop renewal before deciding whether task mutation is still safe.
            # This closes the race where renewal failed as the engine exited.
            if renew_task.done():
                lease_lost = lease_lost or self._renew_result(renew_task)
            else:
                renew_task.cancel()
                try:
                    await renew_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    lease_lost = True

            if self._seconds_remaining(expiry[0]) <= self.lease_safety_seconds:
                lease_lost = True
            if self.stop_requested and not lease_lost:
                try:
                    await asyncio.wait_for(
                        self._release_on_shutdown(proxy, job, expiry[0]),
                        timeout=self.shutdown_grace_seconds,
                    )
                except (TimeoutError, GatewayError, KeyError, TypeError, ValueError):
                    pass
            elif not lease_lost:
                await self._reconcile(proxy, job, exit_code, expiry[0])
        finally:
            if not renew_task.done():
                renew_task.cancel()
            try:
                await renew_task
            except (asyncio.CancelledError, GatewayError):
                pass
            if not engine_task.done():
                await self.engine.terminate()
            if lease_file:
                lease_file.unlink(missing_ok=True)

    async def _renew_loop(self, job: Job, engine_task: asyncio.Task[int], expiry: list[datetime]) -> bool:
        while not engine_task.done() and not self.stop_requested:
            remaining = self._seconds_remaining(expiry[0])
            if remaining <= self.lease_safety_seconds:
                return True
            await self._sleep(max(0.01, min(remaining / 2, remaining - self.lease_safety_seconds)))
            if engine_task.done() or self.stop_requested:
                return False
            backoff = 0.5
            idempotency_key = str(uuid.uuid4())
            while not engine_task.done() and not self.stop_requested:
                if self._seconds_remaining(expiry[0]) <= self.lease_safety_seconds:
                    return True
                try:
                    renewed = await self.gateway.call("tasks_worker_renew", {"job_id": job.job_id, "lease_token": job.lease_token, "idempotency_key": idempotency_key})
                    if not isinstance(renewed, dict):
                        raise GatewayError("mcp_invalid_response")
                    expiry[0] = self._expiry(renewed["lease_expires_at"])
                    break
                except (GatewayError, KeyError, TypeError, ValueError):
                    remaining = self._seconds_remaining(expiry[0]) - self.lease_safety_seconds
                    if remaining <= 0:
                        return True
                    await self._sleep(min(backoff, remaining / 2))
                    backoff = min(5.0, backoff * 2)
        return False

    async def _reconcile(self, proxy: LeasedGatewayProxy, job: Job, exit_code: int, lease_expiry: datetime) -> None:
        task = await self.gateway.call("tasks_get", {"task_id": job.task_id})
        if not isinstance(task, dict):
            raise GatewayError("mcp_invalid_response")
        if await self._release_if_stopping(proxy, job, lease_expiry):
            return
        status, version = task.get("status"), task.get("version")
        if status == "completed":
            await self._finish(job, "completed", version, lease_expiry=lease_expiry)
        elif status == "open" and not task.get("assigned_agent"):
            await self._finish(job, "released", version, lease_expiry=lease_expiry)
        elif status in {"blocked", "waiting_operator"}:
            await self._finish(job, "failed", version, self._error_code(exit_code), lease_expiry)
        elif status in {"claimed", "investigating"}:
            if status == "claimed":
                if await self._release_if_stopping(proxy, job, lease_expiry):
                    return
                task = await proxy.call("tasks_set_status", {"status": "investigating", "expected_version": version})
                if not isinstance(task, dict):
                    raise GatewayError("mcp_invalid_response")
                version = task["version"]
            if await self._release_if_stopping(proxy, job, lease_expiry):
                return
            blocked = await proxy.call("tasks_set_status", {"status": "blocked", "expected_version": version})
            if not isinstance(blocked, dict):
                raise GatewayError("mcp_invalid_response")
            if await self._release_if_stopping(proxy, job, lease_expiry):
                return
            await self._finish(job, "failed", blocked["version"], self._error_code(exit_code), lease_expiry)

    async def _release_if_stopping(self, proxy: LeasedGatewayProxy, job: Job, lease_expiry: datetime) -> bool:
        if not self.stop_requested:
            return False
        await self._release_on_shutdown(proxy, job, lease_expiry)
        return True

    async def _release_on_shutdown(self, proxy: LeasedGatewayProxy, job: Job, lease_expiry: datetime) -> None:
        task = await self.gateway.call("tasks_get", {"task_id": job.task_id})
        if not isinstance(task, dict):
            raise GatewayError("mcp_invalid_response")
        status, version = task.get("status"), task.get("version")
        if status == "completed":
            await self._finish(job, "completed", version, lease_expiry=lease_expiry, abort_on_stop=False)
            return
        if status == "open" and not task.get("assigned_agent"):
            await self._finish(job, "released", version, lease_expiry=lease_expiry, abort_on_stop=False)
            return
        if status in {"claimed", "investigating", "waiting_operator", "blocked"}:
            released = await proxy.call(
                "tasks_release",
                {
                    "expected_version": version,
                    "handoff_summary": "Worker stopped gracefully; task released for operator reassignment.",
                },
            )
            if not isinstance(released, dict):
                raise GatewayError("mcp_invalid_response")
            await self._finish(job, "released", released["version"], lease_expiry=lease_expiry, abort_on_stop=False)

    @staticmethod
    def _error_code(exit_code: int) -> str:
        return "engine_timeout" if exit_code == 124 else "engine_exit_nonzero" if exit_code else "engine_incomplete"

    @staticmethod
    def _expiry(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("lease expiry must include a timezone")
        return parsed

    def _seconds_remaining(self, expiry: datetime) -> float:
        return (expiry - self._now(UTC)).total_seconds()

    @staticmethod
    def _renew_result(task: asyncio.Task[bool]) -> bool:
        try:
            return bool(task.result())
        except (asyncio.CancelledError, Exception):
            return True

    def _create_context(self, job: Job) -> Path | None:
        if self.runtime_dir is None:
            return None
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="lease-", dir=self.runtime_dir)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump({"job_id": job.job_id, "task_id": job.task_id, "lease_token": job.lease_token}, output)
        return Path(name)

    async def _finish(
        self,
        job: Job,
        outcome: str,
        version: int,
        error_code: str = "",
        lease_expiry: datetime | None = None,
        abort_on_stop: bool = True,
    ) -> None:
        idempotency_key = str(uuid.uuid4())
        payload = {
            "job_id": job.job_id,
            "lease_token": job.lease_token,
            "idempotency_key": idempotency_key,
            "outcome": outcome,
            "expected_task_version": version,
            "error_code": error_code,
        }
        for attempt in range(3):
            if abort_on_stop and self.stop_requested:
                return
            if lease_expiry is not None and self._seconds_remaining(lease_expiry) <= self.lease_safety_seconds:
                return
            try:
                await self.gateway.call("tasks_worker_finish", payload)
                return
            except GatewayError as exc:
                if str(exc) not in {"mcp_unavailable", "mcp_invalid_response"} or attempt == 2:
                    raise
                await self._sleep(0.2 * (attempt + 1))
