"""Tool-calling loop shared by the coordinator and every yaver (max `max_steps` LLM turns)."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.agent.context import ToolContext
from app.agent.team import Member
from app.agent.tools import ToolResult, dump_result, run_tool
from app.llm.types import ChatMessage, LLMRequest, LLMResponse, ToolSpec

logger = logging.getLogger(__name__)

Delegate = Callable[[dict[str, Any]], Awaitable[ToolResult]]


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
) -> AgentRun:
    run = AgentRun(member.id, member.name, "")
    history = list(messages)
    tools = member.tool_specs(delegate_spec if delegate else None)

    for _ in range(max_steps):
        ctx.agent_id = ctx.recorder.agent_id = member.id
        response = await llm.complete(
            LLMRequest(
                system=member.system_prompt,
                system_suffix=system_suffix,
                messages=list(history),  # snapshot: history keeps growing
                tools=tools,
                max_tokens=2048,
            ),
            tier=member.tier,
            agent_id=member.id,
            model=member.model,
        )
        run.responses.append(response)
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
            ctx.trace.append(
                {
                    "agent_id": member.id,
                    "tool": call.name,
                    "arguments": call.arguments,
                    "error": result.get("error"),
                }
            )
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
    ctx.agent_id = ctx.recorder.agent_id = member.id
    response = await llm.complete(
        LLMRequest(
            system=member.system_prompt,
            system_suffix=system_suffix,
            messages=list(history),
            tools=tools,
            tool_choice="none",
            max_tokens=1024,
        ),
        tier=member.tier,
        agent_id=member.id,
        model=member.model,
    )
    run.responses.append(response)
    run.reply = response.text.strip()
    return run
