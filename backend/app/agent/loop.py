"""Tool-calling loop shared by the coordinator and every yaver (max `max_steps` LLM turns).

With `emit`, progress is published as events for the streaming chat endpoint:
  {"type": "turn",  "agent_id"}                     a new LLM turn starts (drop draft text)
  {"type": "text",  "agent_id", "delta"}            streamed text (speaker only)
  {"type": "reset", "agent_id"}                     the router retries: drop partial text
  {"type": "tool",  "agent_id", "tool", "arguments", "error", "mutates"}
  {"type": "status", "agent_id", "code": "rate_limited", "provider", "seconds"}  waiting
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agent.context import ToolContext
from app.agent.team import Member
from app.agent.tools import REGISTRY, ToolResult, dump_result, run_tool
from app.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    TextCallback,
    ToolChoice,
    ToolSpec,
)

logger = logging.getLogger(__name__)

Delegate = Callable[[dict[str, Any]], Awaitable[ToolResult]]
Emit = Callable[[dict[str, Any]], Awaitable[None]]


class LLMClient(Protocol):
    async def complete(
        self,
        request: LLMRequest,
        *,
        purpose: str = "chat",
        tier: str | None = None,
        agent_id: str | None = None,
        ignore_budget: bool = False,
        model: str | None = None,
        on_text: TextCallback | None = None,
        on_retry: Callable[[], Awaitable[None]] | None = None,
        on_wait: Callable[[float, str], Awaitable[None]] | None = None,
    ) -> LLMResponse: ...


@dataclass(slots=True)
class AgentRun:
    agent_id: str
    name: str
    reply: str
    responses: list[LLMResponse] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    hit_step_limit: bool = False


async def run_agent(
    llm: LLMClient,
    member: Member,
    messages: list[ChatMessage],
    ctx: ToolContext,
    *,
    system_suffix: str,
    max_steps: int,
    delegate: Delegate | None = None,
    delegate_spec: ToolSpec | None = None,
    emit: Emit | None = None,
    stream_text: bool = False,
) -> AgentRun:
    run = AgentRun(member.id, member.name, "")
    history = list(messages)
    tools = member.tool_specs(delegate_spec if delegate else None)

    async def complete(tool_choice: ToolChoice, max_tokens: int) -> LLMResponse:
        ctx.agent_id = ctx.recorder.agent_id = member.id
        on_text: TextCallback | None = None
        on_retry: Callable[[], Awaitable[None]] | None = None
        on_wait: Callable[[float, str], Awaitable[None]] | None = None
        if emit is not None:
            await emit({"type": "turn", "agent_id": member.id})

            async def send_wait(seconds: float, provider: str) -> None:
                await emit(
                    {
                        "type": "status",
                        "agent_id": member.id,
                        "code": "rate_limited",
                        "provider": provider,
                        "seconds": round(seconds, 1),
                    }
                )

            on_wait = send_wait
            if stream_text:

                async def send_text(delta: str) -> None:
                    await emit({"type": "text", "agent_id": member.id, "delta": delta})

                async def send_reset() -> None:
                    await emit({"type": "reset", "agent_id": member.id})

                on_text, on_retry = send_text, send_reset

        response = await llm.complete(
            LLMRequest(
                system=member.system_prompt,
                system_suffix=system_suffix,
                messages=list(history),  # snapshot: history keeps growing
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
            ),
            tier=member.tier,
            agent_id=member.id,
            model=member.model,
            on_text=on_text,
            on_retry=on_retry,
            on_wait=on_wait,
        )
        run.responses.append(response)
        return response

    for _ in range(max_steps):
        response = await complete("auto", 2048)
        history.append(response.to_message())
        if not response.tool_calls:
            run.reply = response.text.strip()
            return run
        for call in response.tool_calls:
            run.tool_calls.append(call.name)
            if call.name == "delegate" and delegate is not None:
                result = await delegate(call.arguments or {})
            else:
                # A delegate call earlier in this turn may have switched the active yaver.
                ctx.agent_id = ctx.recorder.agent_id = member.id
                result = await run_tool(call.name, call.arguments, ctx)
            step: dict[str, Any] = {
                "agent_id": member.id,
                "tool": call.name,
                "arguments": call.arguments,
                "error": result.get("error"),
            }
            ctx.trace.append(step)
            if emit is not None:
                tool = REGISTRY.get(call.name)
                await emit({"type": "tool", **step, "mutates": bool(tool and tool.mutates)})
            if "error" in result:
                logger.info("%s: %s -> %s", member.id, call.name, result["error"])
            history.append(
                ChatMessage(
                    "tool",
                    dump_result(result),
                    tool_call_id=call.id,
                    is_error="error" in result,
                )
            )

    # Out of steps: one last turn without tools to report what was done.
    run.hit_step_limit = True
    response = await complete("none", 1024)
    run.reply = response.text.strip()
    return run
