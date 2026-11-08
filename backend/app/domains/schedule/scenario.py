"""Deterministic activity delay scenario engine (PI-045).

Rules (01_PRD.md, 02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md, 06_API_SPEC.md):
- User selects activity and delay amount/unit.
- Scenario NEVER mutates source activity/version rows (source_unaltered=True).
- Analyzes float consumption (free float vs total float) and downstream network impact.
- Gracefully returns limited/insufficient_data results when activity is completed or dates missing.
- Transparent assumptions and limitations.
- Hexagonal architecture: zero web, AI, or parser framework dependencies.
"""

import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.schedule.schemas import (
    AffectedScheduleItem,
    DelayScenarioResponse,
    DelayScenarioSummary,
    DelayUnit,
    ImpactType,
)
from app.models.analytics import AnalysisRun
from app.models.project import Project, ProjectVersion
from app.models.schedule import Activity, ActivityRelationship

DEFAULT_HOURS_PER_DAY = 8.0
STANDARD_SCENARIO_ASSUMPTIONS: list[str] = [
    "Working schedule assumes standard 8.0 working hours per day and 5-day working week.",
    (
        "Network dependencies assume Finish-to-Start (FS) logic flow "
        "unless specific relationship dictates otherwise."
    ),
    "No autonomous schedule compression, resource leveling, or activity crashing is assumed.",
]
STANDARD_SCENARIO_LIMITATIONS: list[str] = [
    (
        "Bounded v1 scenario engine: evaluates direct relationships and CPM critical "
        "float propagation without multi-calendar holiday recalculation."
    ),
    (
        "Non-Finish-to-Start relationships (SS, FF, SF) are evaluated using nominal "
        "lag offsets without dynamic sub-activity pacing."
    ),
    "Activities without computed total float are evaluated with limited impact bounds.",
]


async def _resolve_project_version(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Resolve and validate target project version id."""
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version_query = select(ProjectVersion.id).where(
        ProjectVersion.project_id == project_id,
        ProjectVersion.id == target_version_id,
    )
    res = await session.scalar(version_query)
    if not res:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )
    return target_version_id


def _is_milestone(act: Activity) -> bool:
    """Check if activity is a milestone."""
    if act.activity_type:
        norm = act.activity_type.lower()
        if "mile" in norm:
            return True
    if act.original_duration_hours is not None and float(act.original_duration_hours) == 0.0:
        return True
    return False


def _convert_delay(
    delay_value: float,
    delay_unit: DelayUnit,
    hours_per_day: float,
) -> tuple[float, float, int]:
    """Convert delay value and unit into (working_days, hours, calendar_days)."""
    if delay_value <= 0:
        raise ValueError("Delay value must be greater than zero.")

    if delay_unit == "hours":
        hours = round(delay_value, 2)
        working_days = round(delay_value / hours_per_day, 2)
        calendar_days = math.ceil(working_days * (7.0 / 5.0))
    elif delay_unit == "working_days":
        working_days = round(delay_value, 2)
        hours = round(delay_value * hours_per_day, 2)
        calendar_days = math.ceil(working_days * (7.0 / 5.0))
    elif delay_unit == "calendar_days":
        calendar_days = int(math.ceil(delay_value))
        working_days = round(delay_value * (5.0 / 7.0), 2)
        hours = round(working_days * hours_per_day, 2)
    else:
        raise ValueError(f"Unsupported delay unit '{delay_unit}'.")

    return working_days, hours, max(1, calendar_days)


async def simulate_activity_delay(
    session: AsyncSession,
    project_id: uuid.UUID,
    activity_source_id: str,
    delay_value: float,
    delay_unit: DelayUnit = "working_days",
    version_id: uuid.UUID | None = None,
    scenario_name: str = "Delay Simulation",
    hours_per_day: float = DEFAULT_HOURS_PER_DAY,
    persist: bool = True,
    requested_by: uuid.UUID | None = None,
) -> DelayScenarioResponse:
    """Simulate what-if activity delay and compute deterministic network impact (PI-045)."""
    target_version_id = await _resolve_project_version(session, project_id, version_id)

    # 1. Locate target activity
    target_uuid: uuid.UUID | None = None
    try:
        target_uuid = uuid.UUID(activity_source_id)
    except ValueError:
        target_uuid = None

    act_stmt = (
        select(Activity)
        .options(selectinload(Activity.wbs_node))
        .where(
            Activity.project_id == project_id,
            Activity.project_version_id == target_version_id,
        )
    )
    if target_uuid:
        act_stmt = act_stmt.where(
            or_(
                Activity.id == target_uuid,
                Activity.source_activity_id == activity_source_id,
                Activity.activity_code == activity_source_id,
            )
        )
    else:
        act_stmt = act_stmt.where(
            or_(
                Activity.source_activity_id == activity_source_id,
                Activity.activity_code == activity_source_id,
            )
        )

    result = await session.scalars(act_stmt)
    target_act = result.first()
    if not target_act:
        raise ValueError(
            f"Activity '{activity_source_id}' not found in project version '{target_version_id}'."
        )

    # Convert delay metrics
    w_days, h_delay, c_days = _convert_delay(delay_value, delay_unit, hours_per_day)

    # Precondition check: Activity already complete
    act_status = (target_act.status or "unknown").lower()
    if act_status in ("complete", "completed") or target_act.actual_finish is not None:
        return DelayScenarioResponse(
            scenario_name=scenario_name,
            project_id=project_id,
            project_version_id=target_version_id,
            status="insufficient_data",
            summary=DelayScenarioSummary(
                target_activity_id=target_act.id,
                target_activity_code=target_act.activity_code,
                delay_applied_working_days=0.0,
                delay_applied_hours=0.0,
                delay_applied_calendar_days=0,
                free_float_absorbed_hours=0.0,
                total_float_absorbed_hours=0.0,
                critical_path_breached=False,
                net_project_delay_working_days=0.0,
                net_project_delay_calendar_days=0,
                total_affected_activities=0,
                total_affected_milestones=0,
            ),
            affected_items=[],
            assumptions=STANDARD_SCENARIO_ASSUMPTIONS,
            limitations=STANDARD_SCENARIO_LIMITATIONS,
            warnings=[
                (
                    f"Activity '{target_act.activity_code or target_act.source_activity_id}' "
                    "is already completed. Delay simulation is not applicable to historical actual."
                )
            ],
            source_unaltered=True,
        )

    # Precondition check: Anchor date availability
    source_finish = target_act.finish_date or target_act.planned_finish
    source_start = target_act.start_date or target_act.planned_start
    if not source_finish:
        return DelayScenarioResponse(
            scenario_name=scenario_name,
            project_id=project_id,
            project_version_id=target_version_id,
            status="insufficient_data",
            summary=DelayScenarioSummary(
                target_activity_id=target_act.id,
                target_activity_code=target_act.activity_code,
                delay_applied_working_days=0.0,
                delay_applied_hours=0.0,
                delay_applied_calendar_days=0,
                free_float_absorbed_hours=0.0,
                total_float_absorbed_hours=0.0,
                critical_path_breached=False,
                net_project_delay_working_days=0.0,
                net_project_delay_calendar_days=0,
                total_affected_activities=0,
                total_affected_milestones=0,
            ),
            affected_items=[],
            assumptions=STANDARD_SCENARIO_ASSUMPTIONS,
            limitations=STANDARD_SCENARIO_LIMITATIONS,
            warnings=[
                (
                    f"Activity '{target_act.activity_code or target_act.source_activity_id}' "
                    "lacks scheduled start/finish dates to anchor what-if simulation."
                )
            ],
            source_unaltered=True,
        )

    # 2. Compute float absorption and target activity impact
    orig_tf = (
        float(target_act.total_float_hours) if target_act.total_float_hours is not None else None
    )
    orig_ff = float(target_act.free_float_hours) if target_act.free_float_hours is not None else 0.0

    ff_absorbed = min(h_delay, max(0.0, orig_ff))
    if orig_tf is not None:
        tf_absorbed = min(h_delay, max(0.0, orig_tf))
        net_critical_excess_hours = max(0.0, h_delay - max(0.0, orig_tf))
        scenario_remaining_tf = round(orig_tf - h_delay, 2)
    else:
        tf_absorbed = 0.0
        net_critical_excess_hours = h_delay
        scenario_remaining_tf = None

    net_project_delay_w_days = round(net_critical_excess_hours / hours_per_day, 2)
    net_project_delay_c_days = math.ceil(net_project_delay_w_days * (7.0 / 5.0))
    critical_breached = net_critical_excess_hours > 0.0 or (orig_tf is not None and orig_tf <= 0.0)

    scenario_target_finish = source_finish + timedelta(days=c_days)

    affected_items: list[AffectedScheduleItem] = []

    # Add Target Activity
    target_notes = (
        f"Primary delay of {w_days} working days ({h_delay}h, {c_days} calendar days) applied. "
    )
    if orig_tf is not None:
        if net_critical_excess_hours > 0:
            target_notes += (
                f"Exceeds available total float ({orig_tf}h); "
                f"critical path delayed by {net_project_delay_w_days} working days."
            )
        else:
            target_notes += (
                f"Fully absorbed by available total float ({orig_tf}h); "
                f"remaining float is {scenario_remaining_tf}h."
            )
    else:
        target_notes += "Total float unavailable; delay assumed to directly impact critical path."

    target_item = AffectedScheduleItem(
        activity_id=target_act.id,
        source_activity_id=target_act.source_activity_id,
        activity_code=target_act.activity_code,
        activity_name=target_act.activity_name,
        wbs_code=target_act.wbs_node.wbs_code if target_act.wbs_node else None,
        wbs_name=target_act.wbs_node.wbs_name if target_act.wbs_node else None,
        is_milestone=_is_milestone(target_act),
        is_target=True,
        impact_type="primary_delay",
        source_start_date=source_start,
        source_finish_date=source_finish,
        scenario_start_date=source_start,
        scenario_finish_date=scenario_target_finish,
        delay_working_days=w_days,
        delay_calendar_days=c_days,
        original_total_float_hours=orig_tf,
        scenario_remaining_total_float_hours=scenario_remaining_tf,
        notes=target_notes,
    )
    affected_items.append(target_item)

    # 3. Query direct successors
    rel_stmt = select(ActivityRelationship).where(
        ActivityRelationship.project_id == project_id,
        ActivityRelationship.project_version_id == target_version_id,
        ActivityRelationship.predecessor_activity_id == target_act.id,
    )
    rels = list((await session.scalars(rel_stmt)).all())

    succ_ids = [r.successor_activity_id for r in rels]

    succ_acts: list[Activity] = []
    if succ_ids:
        succ_stmt = (
            select(Activity)
            .options(selectinload(Activity.wbs_node))
            .where(
                Activity.project_id == project_id,
                Activity.project_version_id == target_version_id,
                Activity.id.in_(succ_ids),
            )
        )
        succ_acts = list((await session.scalars(succ_stmt)).all())

    succ_by_id = {s.id: s for s in succ_acts}

    processed_succ_ids: set[uuid.UUID] = {target_act.id}

    for rel in rels:
        succ = succ_by_id.get(rel.successor_activity_id)
        if not succ or succ.id in processed_succ_ids:
            continue
        processed_succ_ids.add(succ.id)

        succ_start = succ.start_date or succ.planned_start
        succ_finish = succ.finish_date or succ.planned_finish
        succ_tf = float(succ.total_float_hours) if succ.total_float_hours is not None else None

        lag_days = math.ceil((float(rel.lag_hours or 0.0) / hours_per_day) * (7.0 / 5.0))

        # Check gap between predecessor new finish and successor current start
        if succ_start and source_finish:
            gap_days = max(0, (succ_start - source_finish).days)
        else:
            gap_days = 0

        effective_push_c_days = max(0, c_days - gap_days + lag_days)
        effective_push_w_days = round(effective_push_c_days * (5.0 / 7.0), 2)

        impact_type: ImpactType
        if effective_push_c_days > 0:
            impact_type = "direct_successor_push"
            succ_scenario_start = (
                succ_start + timedelta(days=effective_push_c_days) if succ_start else None
            )
            succ_scenario_finish = (
                succ_finish + timedelta(days=effective_push_c_days) if succ_finish else None
            )
            succ_notes = (
                f"Direct successor linked via {rel.relationship_type or 'FS'}; "
                f"unabsorbed delay pushes start by {effective_push_c_days} calendar days."
            )
        else:
            impact_type = "float_consumption"
            succ_scenario_start = succ_start
            succ_scenario_finish = succ_finish
            succ_notes = (
                f"Delay absorbed by relationship gap/float ({gap_days} calendar days); "
                "successor scheduled start date remains unchanged."
            )

        succ_remaining_tf = (
            round(succ_tf - (effective_push_w_days * hours_per_day), 2)
            if succ_tf is not None
            else None
        )

        affected_items.append(
            AffectedScheduleItem(
                activity_id=succ.id,
                source_activity_id=succ.source_activity_id,
                activity_code=succ.activity_code,
                activity_name=succ.activity_name,
                wbs_code=succ.wbs_node.wbs_code if succ.wbs_node else None,
                wbs_name=succ.wbs_node.wbs_name if succ.wbs_node else None,
                is_milestone=_is_milestone(succ),
                is_target=False,
                impact_type=impact_type,
                source_start_date=succ_start,
                source_finish_date=succ_finish,
                scenario_start_date=succ_scenario_start,
                scenario_finish_date=succ_scenario_finish,
                delay_working_days=effective_push_w_days,
                delay_calendar_days=effective_push_c_days,
                original_total_float_hours=succ_tf,
                scenario_remaining_total_float_hours=succ_remaining_tf,
                notes=succ_notes,
            )
        )

    # 4. Critical downstream milestone impact if critical path breached
    if critical_breached and net_project_delay_c_days > 0:
        ms_stmt = (
            select(Activity)
            .options(selectinload(Activity.wbs_node))
            .where(
                Activity.project_id == project_id,
                Activity.project_version_id == target_version_id,
                or_(
                    Activity.total_float_hours <= 0.0,
                    Activity.total_float_hours.is_(None),
                ),
            )
        )
        crit_acts = list((await session.scalars(ms_stmt)).all())
        for crit in crit_acts:
            if crit.id in processed_succ_ids or not _is_milestone(crit):
                continue
            crit_finish = crit.actual_finish or crit.finish_date or crit.planned_finish
            if crit_finish and source_finish and crit_finish >= source_finish:
                processed_succ_ids.add(crit.id)
                ms_scenario_finish = crit_finish + timedelta(days=net_project_delay_c_days)
                crit_tf = (
                    float(crit.total_float_hours) if crit.total_float_hours is not None else None
                )
                affected_items.append(
                    AffectedScheduleItem(
                        activity_id=crit.id,
                        source_activity_id=crit.source_activity_id,
                        activity_code=crit.activity_code,
                        activity_name=crit.activity_name,
                        wbs_code=crit.wbs_node.wbs_code if crit.wbs_node else None,
                        wbs_name=crit.wbs_node.wbs_name if crit.wbs_node else None,
                        is_milestone=True,
                        is_target=False,
                        impact_type="critical_milestone_slip",
                        source_start_date=crit.start_date or crit.planned_start,
                        source_finish_date=crit_finish,
                        scenario_start_date=crit.start_date or crit.planned_start,
                        scenario_finish_date=ms_scenario_finish,
                        delay_working_days=net_project_delay_w_days,
                        delay_calendar_days=net_project_delay_c_days,
                        original_total_float_hours=crit_tf,
                        scenario_remaining_total_float_hours=(
                            round(crit_tf - (net_project_delay_w_days * hours_per_day), 2)
                            if crit_tf is not None
                            else None
                        ),
                        notes=(
                            "Downstream critical milestone inherits net project critical slip "
                            f"(+{net_project_delay_w_days} working days / "
                            f"{net_project_delay_c_days} calendar days)."
                        ),
                    )
                )

    affected_activities_cnt = sum(1 for it in affected_items if not it.is_milestone)
    affected_milestones_cnt = sum(1 for it in affected_items if it.is_milestone)

    summary = DelayScenarioSummary(
        target_activity_id=target_act.id,
        target_activity_code=target_act.activity_code,
        delay_applied_working_days=w_days,
        delay_applied_hours=h_delay,
        delay_applied_calendar_days=c_days,
        free_float_absorbed_hours=round(ff_absorbed, 2),
        total_float_absorbed_hours=round(tf_absorbed, 2),
        critical_path_breached=critical_breached,
        net_project_delay_working_days=net_project_delay_w_days,
        net_project_delay_calendar_days=net_project_delay_c_days,
        total_affected_activities=affected_activities_cnt,
        total_affected_milestones=affected_milestones_cnt,
    )

    scenario_uuid = uuid.uuid4()

    # 5. Audit persistence in analysis_runs (without mutating source rows)
    if persist:
        run = AnalysisRun(
            id=scenario_uuid,
            workspace_id=target_act.workspace_id,
            project_id=project_id,
            project_version_id=target_version_id,
            analysis_type="delay_scenario",
            engine_name="project_intelligence_deterministic_cpm",
            engine_version="1.0.0",
            method="bounded_cpm_forward_pass",
            parameters={
                "scenario_name": scenario_name,
                "activity_source_id": activity_source_id,
                "delay_value": delay_value,
                "delay_unit": delay_unit,
                "hours_per_day": hours_per_day,
            },
            result={
                "summary": summary.model_dump(mode="json"),
                "affected_items_count": len(affected_items),
            },
            warnings=[],
            status="completed",
            requested_by=requested_by,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        await session.commit()

    return DelayScenarioResponse(
        scenario_id=scenario_uuid,
        scenario_name=scenario_name,
        project_id=project_id,
        project_version_id=target_version_id,
        status="completed",
        summary=summary,
        affected_items=affected_items,
        assumptions=STANDARD_SCENARIO_ASSUMPTIONS,
        limitations=STANDARD_SCENARIO_LIMITATIONS,
        warnings=[],
        source_unaltered=True,
    )
