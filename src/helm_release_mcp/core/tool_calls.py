from typing import Literal, Optional
from pydantic import BaseModel, Field, TypeAdapter
from fastmcp.tools import FunctionTool
from helm_release_mcp.settings import get_settings
from functools import wraps
from typing import Callable, Any
from datetime import datetime, timedelta
import uuid
import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
import json
import aiofiles
import tempfile 


class ToolCall(BaseModel):
    tool_call_id: str
    tool_name: str
    args: dict
    status: Literal["pending", "approved", "rejected"]
    expires: datetime = Field(default_factory=lambda: datetime.now() + timedelta(seconds=120))


class ToolCallStore(ABC):

    _instance: Optional["ToolCallStore"] = None

    @classmethod
    def get_instance(cls) -> "ToolCallStore":
        if cls._instance is not None:
            return cls._instance
        settings = get_settings()
        if settings.tool_call_store_backend == "file":
            cls._instance = FileBasedToolCallStore()
        else:
            raise ValueError(f"Unsupported tool call store backend: {settings.tool_call_store_backend}")

    @abstractmethod
    async def add_tool_call(self, tool_call: ToolCall) -> None:
        pass
    @abstractmethod
    async def get_tool_call(self, tool_call_id: str) -> ToolCall | None:
        pass
    @abstractmethod
    async def list_tool_calls(self) -> list[ToolCall]:
        pass
    @abstractmethod
    async def update_tool_call(self, tool_call: ToolCall) -> None:
        pass
    @abstractmethod
    async def delete_tool_call(self, tool_call_id: str) -> None:
        pass

class FileBasedToolCallStore(ToolCallStore):
    def __init__(self, file_path: Path = Path(tempfile.gettempdir()) / "helm_mcp_tool_calls.json") -> None:
        self.file_path = file_path
        if not self.file_path.exists():
            self.file_path.touch()
        self._cache: list[ToolCall] | None = None
        self._lock = asyncio.Lock()

    async def _load(self) -> list[ToolCall]:
        if self._cache:
            return self._cache
        async with aiofiles.open(self.file_path, "r") as f:
            content = await f.read()
            if not content or content == "null":
                self._cache = []
                return self._cache
            self._cache = TypeAdapter(list[ToolCall]).validate_json(content)
        return self._cache

    async def _flush(self):
        async with aiofiles.open(self.file_path, "wb") as f:
            await f.write(TypeAdapter(list[ToolCall]).dump_json(self._cache))

    async def add_tool_call(self, tool_call: ToolCall) -> None:
        async with self._lock:
            tool_calls = await self._load()
            tool_calls.append(tool_call)
            await self._flush()

    async def get_tool_call(self, tool_call_id: str) -> ToolCall | None:
        async with self._lock:
            tool_calls = await self._load()
            return next((tool_call for tool_call in tool_calls if tool_call.tool_call_id == tool_call_id), None)

    async def list_tool_calls(self) -> list[ToolCall]:
        async with self._lock:
            return await self._load()

    async def update_tool_call(self, tool_call: ToolCall) -> None:
        tool_call_id = tool_call.tool_call_id
        async with self._lock:
            tool_calls = await self._load()
            tool_calls = [tool_call for tool_call in tool_calls if tool_call.tool_call_id != tool_call_id]
            tool_calls.append(tool_call)
            await self._flush()

    async def delete_tool_call(self, tool_call_id: str) -> None:
        async with self._lock:
            tool_calls = await self._load()
            tool_calls = [tool_call for tool_call in tool_calls if tool_call.tool_call_id != tool_call_id]
            self._cache = tool_calls
            await self._flush()

class ToolCallService:
    def __init__(self) -> None:
        self.tool_call_store = ToolCallStore.get_instance()

    async def add_tool_call(self, tool_call: ToolCall) -> None:
        await self.tool_call_store.add_tool_call(tool_call)

    async def get_tool_call(self, tool_call_id: str) -> ToolCall | None:
        return await self.tool_call_store.get_tool_call(tool_call_id)

    async def list_tool_calls(self) -> list[ToolCall]:
        return await self.tool_call_store.list_tool_calls()

    async def approve_tool_call(self, tool_call_id: str) -> None:
        tool_call = await self.get_tool_call(tool_call_id)
        tool_call.status = "approved"
        await self.tool_call_store.update_tool_call(tool_call)

    async def reject_tool_call(self, tool_call_id: str) -> None:
        tool_call = await self.get_tool_call(tool_call_id)
        tool_call.status = "rejected"
        await self.tool_call_store.update_tool_call(tool_call)

    async def delete_tool_call(self, tool_call_id: str) -> None:
        await self.tool_call_store.delete_tool_call(tool_call_id)


class ToolCallApprovalError(Exception):
    """Exception raised when a tool call is rejected or times out."""

    def __init__(self, message: str, tool_call_id: str, tool_name: str) -> None:
        super().__init__(message)
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name


class ToolCallRejectedError(ToolCallApprovalError):
    """Exception raised when a tool call is rejected."""

    pass


class ToolCallTimeoutError(ToolCallApprovalError):
    """Exception raised when a tool call approval times out."""

    pass


tool_call_service = ToolCallService()


def aapprove_required() -> Callable:
    """Decorator that requires approval before executing an MCP tool.

    When a decorated tool is invoked:
    1. Creates a tool call entry in Redis with status "pending"
    2. Blocks and polls until approved/rejected/timeout
    3. If approved, proceeds with execution
    4. If rejected or timeout, raises a human-readable exception

    Args:
        timeout_seconds: Maximum seconds to wait for approval (default: 120).
        poll_interval: Seconds between status checks (default: 0.5).

    Returns:
        Decorator function.

    Raises:
        ToolCallRejectedError: If the tool call is rejected.
        ToolCallTimeoutError: If approval times out.
    """

    def decorator(func: Callable) -> Callable:
        settings = get_settings()
        timeout_seconds = settings.human_in_the_loop_timeout_seconds
        poll_interval = 1

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not settings.human_in_the_loop_enabled:
                return await func(*args, **kwargs)
            tool_name = func.__name__
            tool_call_id = str(uuid.uuid4())

            # Create tool call entry
            tool_call = ToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args={"args": list(args), "kwargs": kwargs},
                status="pending",
                expires=datetime.now() + timedelta(seconds=timeout_seconds),
            )
            await tool_call_service.add_tool_call(tool_call)

            # Poll for approval/rejection/timeout
            start_time = datetime.now()
            while True:
                # Check timeout
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= timeout_seconds:
                    await tool_call_service.delete_tool_call(tool_call_id)
                    raise ToolCallTimeoutError(
                        f"Tool call '{tool_name}' timed out after {timeout_seconds} seconds. "
                        f"Tool call ID: {tool_call_id}",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )

                # Check status
                current_tool_call = await tool_call_service.get_tool_call(tool_call_id)
                if current_tool_call is None:
                    # Tool call was deleted (shouldn't happen, but handle gracefully)
                    raise ToolCallRejectedError(
                        f"Tool call '{tool_name}' was not found. It may have been deleted.",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )

                if current_tool_call.status == "approved":
                    # Clean up and proceed
                    await tool_call_service.delete_tool_call(tool_call_id)
                    return await func(*args, **kwargs)

                if current_tool_call.status == "rejected":
                    # Clean up and raise exception
                    await tool_call_service.delete_tool_call(tool_call_id)
                    raise ToolCallRejectedError(
                        f"Tool call '{tool_name}' was rejected. Tool call ID: {tool_call_id}",
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )

                # Still pending, wait and poll again
                await asyncio.sleep(poll_interval)

        return async_wrapper

    return decorator
