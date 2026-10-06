import asyncio
import json
import time
import os
from pathlib import Path

from backend.app.adapters.workspace.team import (
    close_team,
    load_team,
    make_task,
    validate_components,
)
from .execution_repository import ExecutionConflict, ExecutionRepository


class WorkspaceExecution:
    def __init__(self, directory):
        self.directory = directory
        self.tasks = {}
        self.inputs = {}
        self._repository = None
        self._lock = None

    def repository(self):
        if self._repository is not None:
            return self._repository
        directory = Path(self.directory())
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / "execution-owner.lock").open("a+b")
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise ExecutionConflict(
                "Workspace execution requires one worker; another executor owns this workspace"
            ) from None
        try:
            repo = ExecutionRepository(directory)
            # The OS releases this lock on process exit, unlike a stale PID/expiry lease.
            repo.recover_interrupted()
        except BaseException:
            handle.close()
            raise
        self._lock, self._repository = handle, repo
        return repo

    def start(self, identifier, task, files, environment=()):
        repo = self.repository()
        run = repo.get_run(identifier)
        component = json.loads(run["team_snapshot"])
        validate_components(component)
        message = make_task(task, files)
        repo.claim(identifier, task)
        self.tasks[identifier] = asyncio.create_task(
            self.execute(identifier, run, component, message, environment)
        )
        self.tasks[identifier].add_done_callback(
            lambda _: self.tasks.pop(identifier, None)
        )

    async def execute(self, identifier, run, component, message, environment=()):
        repo = self.repository()
        started = time.monotonic()
        team = None

        async def user_input(prompt, cancellation_token=None):
            pending = asyncio.get_running_loop().create_future()
            self.inputs[identifier] = pending
            repo.event(
                identifier,
                {
                    "type": "input_request",
                    "data": {"prompt": prompt, "source": "user_proxy"},
                },
                "awaiting_input",
            )
            try:
                return await asyncio.wait_for(pending, 1800)
            finally:
                self.inputs.pop(identifier, None)

        try:
            from autogen_agentchat.base import TaskResult
            from autogen_agentchat.messages import ModelClientStreamingChunkEvent

            team = load_team(component, user_input, environment)
            previous = repo.previous_state(run)
            if previous is not None:
                await team.load_state(previous)
            async with asyncio.timeout(3600):
                async for event in team.run_stream(task=message):
                    if isinstance(event, TaskResult):
                        result = {
                            "task_result": {
                                "messages": [],
                                "stop_reason": event.stop_reason,
                            },
                            "duration": time.monotonic() - started,
                            "usage": "",
                        }
                        state = await team.save_state()
                        repo.finish(
                            identifier,
                            "complete",
                            result,
                            state,
                            terminal_event={"type": "result", "data": result},
                        )
                    else:
                        data = event.model_dump(mode="json")
                        if data.get("type") == "UserInputRequestedEvent":
                            continue
                        kind = (
                            "message_chunk"
                            if isinstance(event, ModelClientStreamingChunkEvent)
                            else "message"
                        )
                        repo.event(identifier, {"type": kind, "data": data})
                if repo.get_run(identifier)["status"] not in (
                    "complete",
                    "error",
                    "stopped",
                ):
                    raise RuntimeError("Team stream ended without a result")
        except asyncio.CancelledError:
            repo.finish(
                identifier,
                "stopped",
                {
                    "task_result": {"messages": [], "stop_reason": "Stopped by user"},
                    "duration": time.monotonic() - started,
                },
                terminal_event={
                    "type": "error",
                    "status": "stopped",
                    "error": "Execution stopped",
                },
            )
        except Exception as error:
            # Provider errors can embed credentials/request bodies; expose the type only.
            repo.finish(
                identifier,
                "error",
                {
                    "task_result": {
                        "messages": [],
                        "stop_reason": type(error).__name__,
                    },
                    "duration": time.monotonic() - started,
                },
                terminal_event={
                    "type": "error",
                    "error": f"Execution failed ({type(error).__name__}); check the configured team and provider",
                },
            )
        finally:
            self.inputs.pop(identifier, None)
            if team:
                await close_team(team)

    def input(self, identifier, response):
        pending = self.inputs.get(identifier)
        if pending is None or pending.done():
            raise ExecutionConflict("Run is not waiting for input")
        self.repository().event(identifier, {"type": "input_received"}, "active")
        pending.set_result(response)

    def stop(self, identifier):
        repo = self.repository()
        run = repo.get_run(identifier)
        task = self.tasks.get(identifier)
        if run["status"] not in ("created", "active", "awaiting_input"):
            raise ExecutionConflict("Run is already terminal")
        repo.finish(
            identifier,
            "stopped",
            {"task_result": {"messages": [], "stop_reason": "Stopped"}},
            terminal_event={
                "type": "error",
                "status": "stopped",
                "error": "Execution stopped",
            },
        )
        if task:
            task.cancel()

    async def close(self):
        tasks = list(self.tasks.values())
        for identifier, task in list(self.tasks.items()):
            try:
                self.stop(identifier)
            except (ExecutionConflict, LookupError):
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._lock:
            self._lock.close()
            self._lock = None
        self._repository = None
