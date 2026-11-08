"""Deterministic AI Tool Registry and Execution Dispatcher (PI-041).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Never compute schedule numbers in the AI layer; always delegate to deterministic domain engines.
- Strict server-side context binding: project_id and version_id are injected by the server.
- Tool arguments validated before domain function invocation.
- Captures status, duration, summary, and evidence references.
- Zero dependencies on web framework (fastapi/starlette) or adapters.
"""

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ai.evidence import build_tool_evidence
from app.domains.ai.schemas import (
    AnalyzeQualityArgs,
    CompareVersionsArgs,
    ExportActivityDataArgs,
    GenerateScheduleReportArgs,
    GetActivityDetailArgs,
    GetCriticalActivitiesArgs,
    GetFloatDistributionArgs,
    GetMilestoneForecastArgs,
    GetOverviewArgs,
    GetRelationshipsArgs,
    ListActivitiesArgs,
    SimulateActivityDelayArgs,
    ToolExecutionResult,
)
from app.domains.reporting.service import generate_activity_export, generate_schedule_report
from app.domains.schedule.comparison import compare_versions
from app.domains.schedule.explorer import (
    get_activity_detail,
    get_activity_relationships,
    list_activities,
)
from app.domains.schedule.float_analysis import (
    compute_float_distribution,
    get_critical_exposure_activities,
)
from app.domains.schedule.forecast import compute_milestone_forecast
from app.domains.schedule.metrics import compute_project_overview_metrics
from app.domains.schedule.quality import run_schedule_quality_checks
from app.domains.schedule.scenario import simulate_activity_delay
from app.models.schedule import Activity

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_project_overview",
            "description": (
                "Retrieve high-level project KPI metrics (activity count, status breakdown, "
                "data date, milestone completion) for the selected schedule version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "version_id": {
                        "type": "string",
                        "description": "Optional version UUID. Defaults to active version.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_activities",
            "description": (
                "Search and filter schedule activities by name, code, status, or float threshold."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string",
                        "description": "Text search query on activity code or name",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["not_started", "in_progress", "complete", "suspended"],
                    },
                    "float_max": {"type": "number", "description": "Maximum total float in hours"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_detail",
            "description": (
                "Retrieve detailed information, calendar, dates, float, and source provenance "
                "for a single activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_code": {
                        "type": "string",
                        "description": "Activity code/ID (e.g. A1010)",
                    },
                    "source_activity_id": {
                        "type": "string",
                        "description": "Stable P6 source task ID",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_relationships",
            "description": (
                "Inspect logic links (predecessors and successors, relationship types FS/SS/FF/SF, "
                "and lag hours) for a specified activity."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_code": {
                        "type": "string",
                        "description": "Activity code (e.g. A1010)",
                    },
                    "source_activity_id": {
                        "type": "string",
                        "description": "Stable P6 source task ID",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_critical_activities",
            "description": (
                "List critical and near-critical activities filtered by total float threshold. "
                "Identifies activities with float at or below the threshold."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "float_threshold_hours": {
                        "type": "number",
                        "description": "Critical float threshold in hours (e.g. 0.0)",
                        "default": 0.0,
                    },
                    "near_critical_threshold_hours": {
                        "type": "number",
                        "description": "Near critical float threshold in hours (e.g. 80.0)",
                        "default": 80.0,
                    },
                    "band": {
                        "type": "string",
                        "enum": [
                            "negative_float",
                            "zero_float",
                            "near_critical",
                            "low_float",
                            "high_float",
                        ],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_float_distribution",
            "description": (
                "Retrieve schedule total float histogram bands (negative, zero, near-critical, "
                "low float, high float) and counts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "critical_threshold_hours": {"type": "number", "default": 0.0},
                    "near_critical_threshold_hours": {"type": "number", "default": 80.0},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_schedule_quality",
            "description": (
                "Run schedule quality audit checks (missing links, open ends, orphans, "
                "invalid dates, negative float) and return categorized findings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selected_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of check codes to execute",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["data_quality", "schedule_performance"],
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_project_versions",
            "description": (
                "Compare two schedule versions, returning reconciled additions, removals, "
                "changed dates/float/logic, and ambiguous matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_version_id": {
                        "type": "string",
                        "description": "Baseline/earlier version UUID",
                    },
                    "to_version_id": {
                        "type": "string",
                        "description": "Comparison/target version UUID",
                    },
                    "category_filter": {
                        "type": "string",
                        "enum": ["added", "removed", "changed", "unchanged", "ambiguous"],
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 100},
                },
                "required": ["from_version_id", "to_version_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_milestone_forecast",
            "description": (
                "Retrieve deterministic milestone forecasts and slippage indicators. "
                "Supports 'imported_schedule_dates' (direct P6 forecast dates) or "
                "'deterministic_float_indicator' (slippage projected from negative total float)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["imported_schedule_dates", "deterministic_float_indicator"],
                        "default": "imported_schedule_dates",
                        "description": "Deterministic forecast methodology.",
                    },
                    "milestone_id": {
                        "type": "string",
                        "description": (
                            "Optional specific milestone activity ID, code, or source ID."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simulate_activity_delay",
            "description": (
                "Simulate what-if activity delay and calculate deterministic downstream impact "
                "on float absorption, direct successors, and critical path milestones. "
                "Does not modify source schedule data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_source_id": {
                        "type": "string",
                        "description": "Activity code or source ID to delay.",
                    },
                    "delay_value": {
                        "type": "number",
                        "description": "Delay magnitude (must be positive).",
                    },
                    "delay_unit": {
                        "type": "string",
                        "enum": ["working_days", "calendar_days", "hours"],
                        "default": "working_days",
                        "description": "Unit of delay.",
                    },
                    "scenario_name": {
                        "type": "string",
                        "default": "Delay Simulation",
                        "description": "Descriptive scenario label.",
                    },
                },
                "required": ["activity_source_id", "delay_value"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_schedule_report",
            "description": (
                "Generate a PDF schedule analysis report containing overview, quality "
                "checks, milestone forecasts, and methodology disclaimers (PI-046)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["pdf"],
                        "default": "pdf",
                        "description": "Document output format.",
                    },
                    "include_activity_appendix": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether to append detailed activity tables.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_activity_data",
            "description": (
                "Export filtered activity data in CSV or XLSX tabular format (PI-047). "
                "Supports filters by status, WBS, search text, or critical path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["csv", "xlsx"],
                        "default": "csv",
                        "description": "Tabular export file format.",
                    },
                    "status": {
                        "type": "string",
                        "description": (
                            "Optional status filter "
                            "(e.g., 'not_started', 'in_progress', 'complete')."
                        ),
                    },
                    "wbs_code": {
                        "type": "string",
                        "description": "Optional WBS code prefix filter (e.g., '1.1').",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional activity code or name search query.",
                    },
                    "critical_only": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Whether to export only critical path activities (total float <= 0)."
                        ),
                    },
                },
                "additionalProperties": False,
            },
        },
    },
]

_TOOL_ARG_SCHEMAS: dict[str, type[BaseModel]] = {
    "get_project_overview": GetOverviewArgs,
    "list_activities": ListActivitiesArgs,
    "get_activity_detail": GetActivityDetailArgs,
    "get_activity_relationships": GetRelationshipsArgs,
    "get_critical_activities": GetCriticalActivitiesArgs,
    "get_float_distribution": GetFloatDistributionArgs,
    "analyze_schedule_quality": AnalyzeQualityArgs,
    "compare_project_versions": CompareVersionsArgs,
    "get_milestone_forecast": GetMilestoneForecastArgs,
    "simulate_activity_delay": SimulateActivityDelayArgs,
    "generate_schedule_report": GenerateScheduleReportArgs,
    "export_activity_data": ExportActivityDataArgs,
}


def get_tool_definition(name: str) -> dict[str, Any] | None:
    """Retrieve tool definition schema by name."""
    for tool in TOOL_DEFINITIONS:
        if tool["function"]["name"] == name:
            return tool
    return None


def validate_tool_arguments(tool_name: str, arguments: dict[str, Any] | str) -> BaseModel:
    """Validate and deserialize tool arguments against Pydantic schema."""
    schema_cls = _TOOL_ARG_SCHEMAS.get(tool_name)
    if not schema_cls:
        raise ValueError(f"Unknown tool: '{tool_name}'")

    raw_dict: dict[str, Any]
    if isinstance(arguments, str):
        try:
            raw_dict = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid arguments JSON string for tool '{tool_name}': {exc}"
            ) from exc
    else:
        raw_dict = arguments or {}

    try:
        return schema_cls.model_validate(raw_dict)
    except ValidationError as exc:
        raise ValueError(f"Invalid arguments for tool '{tool_name}': {exc}") from exc


async def _default_in_memory_put(key: str, content: bytes, content_type: str) -> None:
    pass


async def execute_tool(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    tool_name: str,
    arguments: dict[str, Any] | str,
    user_id: uuid.UUID | None = None,
    storage_put_fn: Callable[[str, bytes, str], Awaitable[None]] | None = None,
) -> ToolExecutionResult:
    """Dispatch and execute an approved schedule tool with server-injected project context."""
    start_time = time.perf_counter()

    # 1. Validate tool exists and arguments conform
    try:
        validated_args = validate_tool_arguments(tool_name, arguments)
    except ValueError as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            status="failed",
            tool_name=tool_name,
            summary={"error": str(exc)},
            data={},
            duration_ms=duration_ms,
            error=str(exc),
        )

    # 2. Execute corresponding deterministic schedule engine function
    try:
        data: Any = {}
        summary: dict[str, Any] = {}
        evidence_refs: list[dict[str, Any]] = []

        if tool_name == "get_project_overview":
            args_overview: GetOverviewArgs = validated_args  # type: ignore[assignment]
            target_v = args_overview.version_id or version_id
            overview = await compute_project_overview_metrics(
                session=session,
                project_id=project_id,
                version_id=target_v,
            )
            data = overview.model_dump(mode="json")
            summary = {
                "total_activities": overview.total_activities,
                "data_date": str(overview.data_date) if overview.data_date else None,
                "critical_activities": overview.critical_activities_count,
            }

        elif tool_name == "list_activities":
            args_list: ListActivitiesArgs = validated_args  # type: ignore[assignment]
            act_list = await list_activities(
                session=session,
                project_id=project_id,
                version_id=version_id,
                q=args_list.q,
                status=args_list.status,
                wbs_id=args_list.wbs_id,
                float_max=args_list.float_max,
                limit=args_list.limit,
                offset=args_list.offset,
            )
            data = act_list.model_dump(mode="json")
            summary = {"total_items": act_list.total, "returned_count": len(act_list.items)}

        elif tool_name == "get_activity_detail":
            args_detail: GetActivityDetailArgs = validated_args  # type: ignore[assignment]
            act_id = args_detail.activity_id
            if act_id is None:
                stmt_find = select(Activity.id).where(Activity.project_version_id == version_id)
                if args_detail.activity_code:
                    stmt_find = stmt_find.where(Activity.activity_code == args_detail.activity_code)
                elif args_detail.source_activity_id:
                    stmt_find = stmt_find.where(
                        Activity.source_activity_id == args_detail.source_activity_id
                    )
                act_id = (await session.execute(stmt_find)).scalar_one_or_none()

            if act_id is None:
                data = {"error": "Activity not found for provided identifier(s)."}
                summary = {"status": "not_found"}
            else:
                act_detail = await get_activity_detail(
                    session=session,
                    project_id=project_id,
                    activity_id=act_id,
                    version_id=version_id,
                )
                if act_detail is None:
                    data = {"error": "Activity not found."}
                    summary = {"status": "not_found"}
                else:
                    data = act_detail.model_dump(mode="json")
                    summary = {
                        "activity_code": act_detail.activity_code,
                        "activity_name": act_detail.activity_name,
                        "status": act_detail.status,
                    }

        elif tool_name == "get_activity_relationships":
            args_rels: GetRelationshipsArgs = validated_args  # type: ignore[assignment]
            rel_act_id = args_rels.activity_id
            if rel_act_id is None:
                stmt_find_rel = select(Activity.id).where(Activity.project_version_id == version_id)
                if args_rels.activity_code:
                    stmt_find_rel = stmt_find_rel.where(
                        Activity.activity_code == args_rels.activity_code
                    )
                elif args_rels.source_activity_id:
                    stmt_find_rel = stmt_find_rel.where(
                        Activity.source_activity_id == args_rels.source_activity_id
                    )
                rel_act_id = (await session.execute(stmt_find_rel)).scalar_one_or_none()

            if rel_act_id is None:
                data = {"error": "Activity not found for provided identifier(s)."}
                summary = {"status": "not_found"}
            else:
                rels = await get_activity_relationships(
                    session=session,
                    project_id=project_id,
                    activity_id=rel_act_id,
                    version_id=version_id,
                )
                if rels is None:
                    data = {"error": "Activity relationships not found."}
                    summary = {"status": "not_found"}
                else:
                    data = rels.model_dump(mode="json")
                    summary = {
                        "activity_id": str(rels.activity_id),
                        "predecessor_count": len(rels.predecessors),
                        "successor_count": len(rels.successors),
                    }

        elif tool_name == "get_critical_activities":
            args_crit: GetCriticalActivitiesArgs = validated_args  # type: ignore[assignment]
            crit_resp = await get_critical_exposure_activities(
                session=session,
                project_id=project_id,
                version_id=version_id,
                band=args_crit.band,
                critical_threshold_hours=args_crit.float_threshold_hours,
                near_critical_threshold_hours=args_crit.near_critical_threshold_hours,
                limit=args_crit.limit,
                offset=args_crit.offset,
            )
            data = crit_resp.model_dump(mode="json")
            summary = {
                "total_exposed": crit_resp.total_exposed,
                "returned_count": len(crit_resp.items),
                "critical_threshold_hours": args_crit.float_threshold_hours,
            }

        elif tool_name == "get_float_distribution":
            args_dist: GetFloatDistributionArgs = validated_args  # type: ignore[assignment]
            dist_resp = await compute_float_distribution(
                session=session,
                project_id=project_id,
                version_id=version_id,
                critical_threshold_hours=args_dist.critical_threshold_hours,
                near_critical_threshold_hours=args_dist.near_critical_threshold_hours,
            )
            data = dist_resp.model_dump(mode="json")
            summary = {
                "total_activities": dist_resp.total_activities,
                "activities_with_float": dist_resp.activities_with_float,
                "min_float_hours": dist_resp.min_float_hours,
                "max_float_hours": dist_resp.max_float_hours,
            }

        elif tool_name == "analyze_schedule_quality":
            args_qual: AnalyzeQualityArgs = validated_args  # type: ignore[assignment]
            report = await run_schedule_quality_checks(
                session=session,
                project_id=project_id,
                version_id=version_id,
                selected_checks=args_qual.selected_checks,
                persist=False,
            )
            findings = report.findings
            if args_qual.category:
                findings = [f for f in findings if f.category == args_qual.category]

            data = {
                "summary": report.summary.model_dump(mode="json"),
                "findings": [f.model_dump(mode="json") for f in findings],
            }
            summary = {
                "total_findings": report.summary.total_findings,
                "data_quality_count": report.summary.data_quality_count,
                "schedule_performance_count": report.summary.schedule_performance_count,
            }

        elif tool_name == "compare_project_versions":
            args_comp: CompareVersionsArgs = validated_args  # type: ignore[assignment]
            comp_report = await compare_versions(
                session=session,
                project_id=project_id,
                from_version_id=args_comp.from_version_id,
                to_version_id=args_comp.to_version_id,
                category_filter=args_comp.category_filter,  # type: ignore[arg-type]
                limit=args_comp.limit,
                offset=args_comp.offset,
            )
            data = comp_report.model_dump(mode="json")
            summary = comp_report.summary.model_dump(mode="json")

        elif tool_name == "get_milestone_forecast":
            args_fc: GetMilestoneForecastArgs = validated_args  # type: ignore[assignment]
            fc_report = await compute_milestone_forecast(
                session=session,
                project_id=project_id,
                version_id=version_id,
                method=args_fc.method,
                milestone_id=args_fc.milestone_id,
            )
            data = fc_report.model_dump(mode="json")
            summary = {
                "total_milestones": fc_report.summary.total_milestones,
                "completed_milestones": fc_report.summary.completed_milestones,
                "critical_milestones": fc_report.summary.critical_milestones,
                "delayed_or_slipping_milestones": fc_report.summary.delayed_or_slipping_milestones,
                "method": fc_report.method,
            }

        elif tool_name == "simulate_activity_delay":
            args_scen: SimulateActivityDelayArgs = validated_args  # type: ignore[assignment]
            scen_report = await simulate_activity_delay(
                session=session,
                project_id=project_id,
                activity_source_id=args_scen.activity_source_id,
                delay_value=args_scen.delay_value,
                delay_unit=args_scen.delay_unit,
                version_id=version_id,
                scenario_name=args_scen.scenario_name,
                persist=True,
            )
            data = scen_report.model_dump(mode="json")
            summary = {
                "scenario_name": scen_report.scenario_name,
                "status": scen_report.status,
                "target_activity_code": scen_report.summary.target_activity_code,
                "delay_applied_working_days": scen_report.summary.delay_applied_working_days,
                "critical_path_breached": scen_report.summary.critical_path_breached,
                "net_project_delay_working_days": (
                    scen_report.summary.net_project_delay_working_days
                ),
                "total_affected_items": len(scen_report.affected_items),
            }

        elif tool_name == "generate_schedule_report":
            args_rep: GenerateScheduleReportArgs = validated_args  # type: ignore[assignment]
            put_fn = storage_put_fn or _default_in_memory_put
            report_record = await generate_schedule_report(
                session=session,
                storage_put_fn=put_fn,
                project_id=project_id,
                version_id=version_id,
                user_id=user_id,
                report_type="schedule_analysis",
                output_format="pdf",
                options={"include_activity_appendix": args_rep.include_activity_appendix},
            )
            data = {
                "id": str(report_record.id),
                "title": report_record.title,
                "status": report_record.status,
                "output_format": report_record.output_format,
                "object_key": report_record.object_key,
                "project_version_id": str(report_record.project_version_id),
            }
            summary = {
                "report_id": str(report_record.id),
                "status": report_record.status,
                "output_format": report_record.output_format,
                "title": report_record.title,
            }

        elif tool_name == "export_activity_data":
            args_exp: ExportActivityDataArgs = validated_args  # type: ignore[assignment]
            put_fn = storage_put_fn or _default_in_memory_put
            report_record = await generate_activity_export(
                session=session,
                storage_put_fn=put_fn,
                project_id=project_id,
                version_id=version_id,
                user_id=user_id,
                output_format=args_exp.format,
                status_filter=args_exp.status,
                wbs_code_filter=args_exp.wbs_code,
                search_query=args_exp.search,
                critical_only=args_exp.critical_only,
            )
            data = {
                "id": str(report_record.id),
                "title": report_record.title,
                "status": report_record.status,
                "output_format": report_record.output_format,
                "object_key": report_record.object_key,
                "project_version_id": str(report_record.project_version_id),
            }
            summary = {
                "report_id": str(report_record.id),
                "status": report_record.status,
                "output_format": report_record.output_format,
                "title": report_record.title,
            }

        # Extract structured evidence references from deterministic data (PI-042)
        raw_evidence = build_tool_evidence(tool_name, version_id, data)
        evidence_refs = [ref.model_dump(mode="json") for ref in raw_evidence]

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            status="completed",
            tool_name=tool_name,
            summary=summary,
            data=data,
            evidence_refs=evidence_refs,
            duration_ms=duration_ms,
        )

    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            status="failed",
            tool_name=tool_name,
            summary={"error": str(exc)},
            data={},
            duration_ms=duration_ms,
            error=str(exc),
        )
