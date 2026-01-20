from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from pydantic import BaseModel

from helm_release_mcp.api import verify_token
from helm_release_mcp.core.tool_calls import ToolCallService, ToolCall

router = APIRouter()
tool_call_service = ToolCallService()


class ToolCallItem(BaseModel):
    tool_call_id: str
    tool_name: str
    args: dict
    status: str


class ToolCallResponse(BaseModel):
    items: list[ToolCallItem]


class ToolCallActionRequest(BaseModel):
    action: str  # "approve" or "reject"


@router.get("/api/tool-calls")
async def api_tool_calls(_: Annotated[str, Depends(verify_token)]) -> ToolCallResponse:
    """Get all tool calls."""
    tool_calls = await tool_call_service.list_tool_calls()
    return ToolCallResponse(
        items=[
            ToolCallItem(
                tool_call_id=tc.tool_call_id,
                tool_name=tc.tool_name,
                args=tc.args,
                status=tc.status,
            )
            for tc in tool_calls
        ],
    )


@router.get("/api/tool-calls/{tool_call_id}")
async def api_get_tool_call(
    tool_call_id: str,
    _: Annotated[str, Depends(verify_token)],
) -> ToolCallItem:
    """Get a specific tool call."""
    tool_call = await tool_call_service.get_tool_call(tool_call_id)
    if tool_call is None:
        raise HTTPException(status_code=404, detail="Tool call not found")
    return ToolCallItem(
        tool_call_id=tool_call.tool_call_id,
        tool_name=tool_call.tool_name,
        args=tool_call.args,
        status=tool_call.status,
    )


@router.post("/api/tool-calls/{tool_call_id}/approve")
async def api_approve_tool_call(
    tool_call_id: str,
    _: Annotated[str, Depends(verify_token)],
) -> dict:
    """Approve a tool call."""
    try:
        await tool_call_service.approve_tool_call(tool_call_id)
        return {"success": True, "message": "Tool call approved"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/tool-calls/{tool_call_id}/reject")
async def api_reject_tool_call(
    tool_call_id: str,
    _: Annotated[str, Depends(verify_token)],
) -> dict:
    """Reject a tool call."""
    try:
        await tool_call_service.reject_tool_call(tool_call_id)
        return {"success": True, "message": "Tool call rejected"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/api/tool-calls/{tool_call_id}")
async def api_delete_tool_call(
    tool_call_id: str,
    _: Annotated[str, Depends(verify_token)],
) -> dict:
    """Delete a tool call."""
    await tool_call_service.delete_tool_call(tool_call_id)
    return {"success": True, "message": "Tool call deleted"}
