import asyncio
import json
import uuid
from contextlib import AsyncExitStack
from datetime import timedelta
from urllib.parse import urlsplit


def validate_params(params):
    if len(json.dumps(params)) > 64000:
        raise ValueError("MCP configuration is too large")
    kind = params.get("type")
    if kind == "StdioServerParams":
        if not isinstance(params.get("command"), str) or not params["command"].strip():
            raise ValueError("MCP command is required")
        if not isinstance(params.get("args", []), list) or not all(
            isinstance(x, str) for x in params.get("args", [])
        ):
            raise ValueError("MCP args must be strings")
    elif kind in ("SseServerParams", "StreamableHttpServerParams"):
        if not isinstance(params.get("url"), str):
            raise ValueError("MCP URL must be a string")
        url = urlsplit(params.get("url", ""))
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("MCP requires an HTTP(S) URL without embedded credentials")
    else:
        raise ValueError("Unsupported MCP transport")
    for name in ("env", "headers"):
        if name in params and (
            not isinstance(params[name], dict)
            or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in params[name].items()
            )
        ):
            raise ValueError(f"MCP {name} must contain strings")


class McpConnections:
    def __init__(self):
        self.connections = {}

    async def connect(self, params):
        validate_params(params)
        if len(self.connections) >= 16:
            raise ValueError(
                "Disconnect an MCP server before opening another connection"
            )
        identifier = uuid.uuid4().hex
        queue = asyncio.Queue(maxsize=16)
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self.actor(params, queue, ready))
        self.connections[identifier] = (queue, task)
        task.add_done_callback(lambda _: self.connections.pop(identifier, None))
        try:
            capabilities = await asyncio.wait_for(asyncio.shield(ready), 20)
            return {"connection_id": identifier, "capabilities": capabilities}
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if ready.done() and not ready.cancelled():
                ready.exception()
            raise

    async def actor(self, params, queue, ready):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.sse import sse_client
        from mcp.client.streamable_http import streamablehttp_client

        current_future = None
        try:
            async with AsyncExitStack() as stack:
                kind = params["type"]
                if kind == "StdioServerParams":
                    # The SDK uses CREATE_NO_WINDOW and a Windows job object.
                    transport = stdio_client(
                        StdioServerParameters(
                            command=params["command"],
                            args=params.get("args", []),
                            env=params.get("env"),
                        )
                    )
                elif kind == "SseServerParams":
                    transport = sse_client(
                        params["url"], headers=params.get("headers"), timeout=15
                    )
                else:
                    transport = streamablehttp_client(
                        params["url"], headers=params.get("headers"), timeout=15
                    )
                streams = await stack.enter_async_context(transport)
                session = await stack.enter_async_context(
                    ClientSession(
                        streams[0],
                        streams[1],
                        read_timeout_seconds=timedelta(seconds=45),
                    )
                )
                info = await session.initialize()
                ready.set_result(
                    info.capabilities.model_dump(mode="json", exclude_none=True)
                )
                while True:
                    try:
                        operation, future = await asyncio.wait_for(queue.get(), 300)
                        current_future = future
                    except TimeoutError:
                        return
                    if operation is None:
                        future.set_result(None)
                        return
                    if future.cancelled():
                        continue
                    try:
                        name = operation["operation"]
                        if name == "list_tools":
                            result = await session.list_tools()
                        elif name == "call_tool":
                            result = await session.call_tool(
                                operation["tool_name"], operation.get("arguments", {})
                            )
                        elif name == "list_resources":
                            result = await session.list_resources()
                        elif name == "read_resource":
                            result = await session.read_resource(operation["uri"])
                        else:
                            raise ValueError("Unknown MCP operation")
                        if not future.done():
                            future.set_result(
                                {
                                    "type": "operation_result",
                                    "operation": name,
                                    "data": result.model_dump(
                                        mode="json", by_alias=True, exclude_none=True
                                    ),
                                }
                            )
                    except Exception as error:
                        if not future.done():
                            future.set_result(
                                {
                                    "type": "operation_error",
                                    "operation": operation["operation"],
                                    "error": f"MCP operation failed ({type(error).__name__})",
                                }
                            )
        except BaseException as error:
            if not ready.done():
                ready.set_exception(
                    RuntimeError(f"MCP initialization failed ({type(error).__name__})")
                )
        finally:
            if current_future is not None and not current_future.done():
                current_future.set_exception(
                    RuntimeError(
                        "MCP connection closed during operation; completion is unknown"
                    )
                )
            while not queue.empty():
                _, future = queue.get_nowait()
                if not future.done():
                    future.set_exception(RuntimeError("MCP connection closed"))

    async def operation(self, identifier, body):
        connection = self.connections.get(identifier)
        if connection is None or connection[1].done():
            raise LookupError("MCP connection not found; reconnect")
        future = asyncio.get_running_loop().create_future()
        try:
            connection[0].put_nowait((body, future))
        except asyncio.QueueFull:
            raise ValueError("MCP operation queue is full") from None
        try:
            return await asyncio.wait_for(future, 55)
        except TimeoutError:
            await self.disconnect(identifier)
            raise RuntimeError(
                "MCP operation timed out; completion is unknown and connection was closed"
            ) from None

    async def disconnect(self, identifier):
        connection = self.connections.get(identifier)
        if connection is None:
            raise LookupError("MCP connection not found")
        task = connection[1]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.connections.pop(identifier, None)

    async def close(self):
        tasks = [task for _, task in self.connections.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.connections.clear()
