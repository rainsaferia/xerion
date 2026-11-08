"""Project AI Orchestrator core service (PI-041).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Server context binding: project_id, version_id, workspace_id are injected by the server.
- Strict multi-turn execution loop: LLM initiates tool calls, domain tools execute.
- Zero direct schedule calculations in the AI layer; always route to approved deterministic tools.
- Complete audit trace of all messages and tool executions persisted to database.
- Domain isolation: zero dependencies on web framework (fastapi) or external vendor adapters.
"""

import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.ai.evidence import EvidenceReference
from app.domains.ai.schemas import (
    AgentTurnResponse,
    ConversationResponse,
    MessageItem,
    ToolExecutionItem,
    ToolExecutionResult,
)
from app.domains.ai.tools import TOOL_DEFINITIONS, execute_tool
from app.domains.ai.validator import validate_assistant_response
from app.models.ai import AIConversation, AIMessage, AIToolExecution
from app.models.project import Project, ProjectVersion


@runtime_checkable
class LLMClientProtocol(Protocol):
    """Protocol for LLM client adapter."""

    async def complete(
        self,
        messages: list[Any],
        tools: list[Any] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> Any: ...


class DialogueMessage(BaseModel):
    """Internal message representation decoupling domain from adapter contracts."""

    model_config = ConfigDict(frozen=True)

    role: str
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[Any] | None = None


SYSTEM_PROMPT_TEMPLATE = """You are the Project Intelligence Assistant for EPC professionals.

Current Server Context:
- Project ID: {project_id}
- Target Schedule Version ID: {version_id}

CRITICAL RULES:
1. Always use approved tools to inspect activities, calculate float, and check quality.
2. Never invent, estimate, or calculate schedule numbers, critical paths, or dates from memory.
3. Do not run SQL queries or attempt to access files directly.
4. Distinguish clearly between facts imported from Primavera P6 and calculated metrics.
5. If a tool reports missing or insufficient data, inform the user honestly about data limitations.
6. Cite specific evidence tags provided in tool outputs like [EV: ...] when quoting metrics.
"""


async def create_conversation(
    session: AsyncSession,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str | None = None,
    version_id: uuid.UUID | None = None,
) -> ConversationResponse:
    """Create a new AI conversation scoped to a project."""
    conv = AIConversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        created_by=user_id,
        title=title or "New Schedule Conversation",
        selected_project_version_id=version_id,
        status="active",
    )
    session.add(conv)
    await session.commit()
    await session.refresh(conv)

    return ConversationResponse(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        selected_project_version_id=conv.selected_project_version_id,
        status=conv.status,
        messages=[],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


async def list_conversations(
    session: AsyncSession,
    project_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationResponse]:
    """List conversations for a project ordered by most recently updated."""
    query = (
        select(AIConversation)
        .where(AIConversation.project_id == project_id)
        .order_by(AIConversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await session.execute(query)
    conversations = res.scalars().all()

    return [
        ConversationResponse(
            id=c.id,
            project_id=c.project_id,
            title=c.title,
            selected_project_version_id=c.selected_project_version_id,
            status=c.status,
            messages=[],
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conversations
    ]


async def get_conversation(
    session: AsyncSession,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> ConversationResponse:
    """Retrieve full conversation history including messages and tool executions."""
    query = (
        select(AIConversation)
        .where(
            AIConversation.id == conversation_id,
            AIConversation.project_id == project_id,
        )
        .options(selectinload(AIConversation.messages).selectinload(AIMessage.tool_executions))
    )
    res = await session.execute(query)
    conv = res.scalar_one_or_none()
    if not conv:
        raise ValueError(f"Conversation '{conversation_id}' not found for project '{project_id}'")

    messages_out: list[MessageItem] = []
    for m in conv.messages:
        tools_out: list[ToolExecutionItem] = [
            ToolExecutionItem(
                id=t.id,
                tool_name=t.tool_name,
                arguments=t.arguments,
                output_summary=t.output_summary,
                status=t.status,
                duration_ms=t.duration_ms,
            )
            for t in m.tool_executions
        ]
        messages_out.append(
            MessageItem(
                id=m.id,
                role=m.role,
                content=m.content,
                tool_executions=tools_out,
                created_at=m.created_at,
            )
        )

    return ConversationResponse(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        selected_project_version_id=conv.selected_project_version_id,
        status=conv.status,
        messages=messages_out,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


async def run_agent_turn(
    session: AsyncSession,
    llm_client: LLMClientProtocol,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message_text: str,
    target_version_id: uuid.UUID | None = None,
    max_turns: int = 5,
    storage_put_fn: Callable[[str, bytes, str], Awaitable[None]] | None = None,
) -> AgentTurnResponse:
    """Execute a single user agent turn, handling tool execution cycles and persistence."""
    # 1. Fetch conversation
    query = (
        select(AIConversation)
        .where(
            AIConversation.id == conversation_id,
            AIConversation.project_id == project_id,
        )
        .options(selectinload(AIConversation.messages).selectinload(AIMessage.tool_executions))
    )
    res = await session.execute(query)
    conv = res.scalar_one_or_none()
    if not conv:
        raise ValueError(f"Conversation '{conversation_id}' not found for project '{project_id}'")

    # 2. Resolve target schedule version
    resolved_version_id = target_version_id or conv.selected_project_version_id
    if not resolved_version_id:
        proj_res = await session.execute(select(Project).where(Project.id == project_id))
        project = proj_res.scalar_one_or_none()
        if project and project.latest_version_id:
            resolved_version_id = project.latest_version_id
        else:
            v_res = await session.execute(
                select(ProjectVersion)
                .where(
                    ProjectVersion.project_id == project_id,
                    ProjectVersion.status == "ready",
                )
                .order_by(ProjectVersion.version_number.desc())
            )
            v = v_res.scalars().first()
            if not v:
                raise ValueError("No ready schedule version found for this project.")
            resolved_version_id = v.id

    conv.selected_project_version_id = resolved_version_id

    # 3. Persist incoming user message
    user_msg = AIMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        workspace_id=workspace_id,
        project_id=project_id,
        project_version_id=resolved_version_id,
        role="user",
        content=user_message_text,
    )
    session.add(user_msg)
    await session.flush()

    # 4. Assemble dialogue messages for LLM
    dialogue: list[Any] = [
        DialogueMessage(
            role="system",
            content=SYSTEM_PROMPT_TEMPLATE.format(
                project_id=str(project_id),
                version_id=str(resolved_version_id),
            ),
        )
    ]

    # Include recent conversation history
    for m in conv.messages[-10:]:
        dialogue.append(
            DialogueMessage(
                role=m.role,
                content=m.content,
            )
        )
    dialogue.append(DialogueMessage(role="user", content=user_message_text))

    # 5. Multi-turn execution loop
    turn_tool_executions: list[AIToolExecution] = []
    accumulated_evidence: list[EvidenceReference] = []
    final_content: str | None = None
    provider_name = "unknown"
    model_name = "unknown"
    tokens_accumulated = 0
    total_latency_ms = 0

    for _ in range(max_turns):
        completion = await llm_client.complete(
            messages=dialogue,
            tools=TOOL_DEFINITIONS,
            temperature=0.0,
        )
        provider_name = getattr(completion, "provider", "unknown")
        model_name = getattr(completion, "model", "unknown")
        tokens_accumulated += getattr(getattr(completion, "usage", None), "total_tokens", 0)
        total_latency_ms += getattr(completion, "latency_ms", 0)

        # Case A: Model requested tool calls
        if getattr(completion, "tool_calls", None):
            assistant_content = getattr(completion.message, "content", None)
            tool_calls = completion.tool_calls

            # Append assistant message with tool calls to dialogue
            dialogue.append(
                DialogueMessage(
                    role="assistant",
                    content=assistant_content,
                    tool_calls=tool_calls,
                )
            )

            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = tc.function.arguments

                tool_result: ToolExecutionResult = await execute_tool(
                    session=session,
                    project_id=project_id,
                    version_id=resolved_version_id,
                    tool_name=fn_name,
                    arguments=fn_args,
                    user_id=user_id,
                    storage_put_fn=storage_put_fn,
                )

                # Track tool execution for persistence
                raw_args = fn_args
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except Exception:
                        raw_args = {"raw": raw_args}

                tool_exec = AIToolExecution(
                    id=uuid.uuid4(),
                    message_id=user_msg.id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_version_id=resolved_version_id,
                    tool_name=fn_name,
                    arguments=raw_args,
                    output_summary=tool_result.summary,
                    evidence_refs=tool_result.evidence_refs,
                    status=tool_result.status,
                    duration_ms=tool_result.duration_ms,
                )
                turn_tool_executions.append(tool_exec)

                for ref_dict in tool_result.evidence_refs:
                    with contextlib.suppress(Exception):
                        accumulated_evidence.append(EvidenceReference.model_validate(ref_dict))

                # Return tool output into dialogue
                tool_payload_str = (
                    json.dumps(tool_result.data)
                    if tool_result.status == "completed"
                    else json.dumps({"error": tool_result.error})
                )
                dialogue.append(
                    DialogueMessage(
                        role="tool",
                        content=tool_payload_str,
                        tool_call_id=tc.id,
                    )
                )

            # Continue loop for model to process tool outputs
            continue

        # Case B: Model returned final text answer
        final_content = getattr(completion.message, "content", None)
        break

    if final_content is None:
        final_content = "Analysis completed. However, no final summary was generated."

    # 5b. Validate assistant response against evidence and executed tools (PI-042)
    turn_tool_dicts = [
        {"tool_name": te.tool_name, "status": te.status, "output_summary": te.output_summary}
        for te in turn_tool_executions
    ]
    validated = validate_assistant_response(
        response_text=final_content,
        tools_executed=turn_tool_dicts,
        accumulated_evidence=accumulated_evidence,
    )
    final_content = validated.content

    # 6. Persist final assistant message
    asst_msg = AIMessage(
        id=uuid.uuid4(),
        conversation_id=conv.id,
        workspace_id=workspace_id,
        project_id=project_id,
        project_version_id=resolved_version_id,
        role="assistant",
        content=final_content,
        provider=provider_name,
        model=model_name,
        token_input=tokens_accumulated,
        token_output=0,
    )
    session.add(asst_msg)
    await session.flush()

    # Re-link tool executions to final assistant message and add to session
    for te in turn_tool_executions:
        te.message_id = asst_msg.id
        session.add(te)

    await session.commit()
    await session.refresh(asst_msg)

    tool_items_out = [
        ToolExecutionItem(
            id=te.id,
            tool_name=te.tool_name,
            arguments=te.arguments,
            output_summary=te.output_summary,
            status=te.status,
            duration_ms=te.duration_ms,
            evidence_refs=te.evidence_refs or [],
        )
        for te in turn_tool_executions
    ]

    return AgentTurnResponse(
        conversation_id=conv.id,
        message=MessageItem(
            id=asst_msg.id,
            role=asst_msg.role,
            content=asst_msg.content,
            tool_executions=tool_items_out,
            created_at=asst_msg.created_at,
        ),
        tool_executions=tool_items_out,
        provider=provider_name,
        model=model_name,
        validation_status=validated.validation_status,
        evidence_citations=validated.evidence_citations,
        warnings=validated.warnings,
        tokens_used=tokens_accumulated,
        latency_ms=total_latency_ms,
    )
