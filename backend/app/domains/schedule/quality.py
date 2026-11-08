"""Deterministic schedule quality check engine (PI-033).

Rules (02_SYSTEM_ARCHITECTURE.md, 03_DATA_MODEL.md, 08_DEVELOPMENT_BACKLOG.md PI-033):
- Implements only explicitly documented checks:
    1. Missing IDs / Codes (data_quality)
    2. Duplicate Activity Codes (data_quality)
    3. Orphan Relationships (data_quality)
    4. Invalid Date Ranges (data_quality)
    5. Missing Predecessors / Open Start (data_quality)
    6. Missing Successors / Open Finish (data_quality)
    7. Invalid Progress % (data_quality)
    8. Negative Total Float (schedule_performance)
    9. High Total Float (schedule_performance)
- Strictly distinguishes data-quality checks from schedule-performance findings.
- Each finding documents: check_code, category, severity, method, limitation, evidence.
- Start and finish milestones are properly handled during open-ends checks.
- Optional persistence to AnalysisRun and AnalysisFinding models.
- Domain isolation: no web/API framework imports.
"""

import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    QualityCheckReport,
    QualityCheckSummary,
    QualityFindingItem,
)
from app.models.analytics import AnalysisFinding, AnalysisRun
from app.models.project import Project, ProjectVersion
from app.models.schedule import Activity, ActivityRelationship


async def run_schedule_quality_checks(
    session: AsyncSession,
    project_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    selected_checks: list[str] | None = None,
    persist: bool = True,
    requested_by: uuid.UUID | None = None,
) -> QualityCheckReport:
    """Run deterministic schedule quality audit against a confirmed project version."""
    project = await session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project '{project_id}' not found.")

    target_version_id = version_id or project.latest_version_id
    if not target_version_id:
        raise ValueError(f"Project '{project_id}' has no ready versions.")

    version = await session.get(ProjectVersion, target_version_id)
    if not version or version.project_id != project_id:
        raise ValueError(
            f"ProjectVersion '{target_version_id}' not found for project '{project_id}'."
        )

    # 1. Fetch activities and relationships for the target version
    act_query = (
        select(Activity)
        .where(Activity.project_version_id == target_version_id)
        .order_by(Activity.activity_code.asc())
    )
    activities = list((await session.scalars(act_query)).all())

    rel_query = select(ActivityRelationship).where(
        ActivityRelationship.project_version_id == target_version_id
    )
    relationships = list((await session.scalars(rel_query)).all())

    findings: list[QualityFindingItem] = []
    checks_run: list[str] = []

    def _should_run(name: str) -> bool:
        return selected_checks is None or name in selected_checks

    activity_by_id = {act.id: act for act in activities}
    activity_ids = set(activity_by_id.keys())

    # -----------------------------------------------------------------------
    # 1. Check: missing_activity_identifier (Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("missing_activity_identifier"):
        checks_run.append("missing_activity_identifier")
        for act in activities:
            src_empty = not act.source_activity_id or not act.source_activity_id.strip()
            code_empty = not act.activity_code or not act.activity_code.strip()
            if src_empty or code_empty:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="missing_activity_identifier",
                        category="data_quality",
                        title="Missing Activity Identifier",
                        severity="high",
                        method="activity_identifier_null_or_empty_check",
                        limitation="Evaluates activity_code and source_activity_id fields",
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_name}' is missing source ID or activity code."
                        ),
                        evidence=[
                            {"field": "source_activity_id", "value": act.source_activity_id},
                            {"field": "activity_code", "value": act.activity_code},
                            {"field": "activity_name", "value": act.activity_name},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 2. Check: duplicate_activity_identifier (Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("duplicate_activity_identifier"):
        checks_run.append("duplicate_activity_identifier")
        code_counts = Counter(
            act.activity_code
            for act in activities
            if act.activity_code and act.activity_code.strip()
        )
        duplicates = {c: cnt for c, cnt in code_counts.items() if cnt > 1}
        for act in activities:
            if act.activity_code in duplicates:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="duplicate_activity_identifier",
                        category="data_quality",
                        title=f"Duplicate Activity Code: {act.activity_code}",
                        severity="high",
                        method="activity_code_uniqueness_grouping",
                        limitation=(
                            "Evaluates unique activity_code within confirmed version lineage"
                        ),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity code '{act.activity_code}' appears "
                            f"{duplicates[act.activity_code]} times in this version."
                        ),
                        evidence=[
                            {"field": "activity_code", "value": act.activity_code},
                            {"field": "duplicate_count", "value": duplicates[act.activity_code]},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 3. Check: orphan_relationships (Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("orphan_relationships"):
        checks_run.append("orphan_relationships")
        for rel in relationships:
            if rel.is_external:
                continue

            pred_missing = rel.predecessor_activity_id not in activity_ids
            succ_missing = rel.successor_activity_id not in activity_ids

            if pred_missing or succ_missing:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="orphan_relationships",
                        category="data_quality",
                        title="Orphan Relationship Link",
                        severity="critical",
                        method="relationship_endpoint_id_referential_integrity",
                        limitation=(
                            "Checks endpoints within version; excludes marked external links"
                        ),
                        entity_type="relationship",
                        entity_id=rel.id,
                        entity_source_id=rel.source_relationship_id,
                        entity_code=None,
                        message=(
                            f"Relationship links predecessor '{rel.predecessor_activity_id}' "
                            f"to successor '{rel.successor_activity_id}', "
                            "but one or both do not exist in this version."
                        ),
                        evidence=[
                            {"field": "relationship_id", "value": str(rel.id)},
                            {"field": "predecessor_id", "value": str(rel.predecessor_activity_id)},
                            {"field": "successor_id", "value": str(rel.successor_activity_id)},
                            {"field": "predecessor_missing", "value": pred_missing},
                            {"field": "successor_missing", "value": succ_missing},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 4. Check: invalid_date_range (Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("invalid_date_range"):
        checks_run.append("invalid_date_range")
        for act in activities:
            date_errs = []
            if act.finish_date and act.start_date and act.finish_date < act.start_date:
                date_errs.append(("start_date", "finish_date", act.start_date, act.finish_date))
            if act.planned_finish and act.planned_start and act.planned_finish < act.planned_start:
                date_errs.append(
                    ("planned_start", "planned_finish", act.planned_start, act.planned_finish)
                )
            if act.actual_finish and act.actual_start and act.actual_finish < act.actual_start:
                date_errs.append(
                    ("actual_start", "actual_finish", act.actual_start, act.actual_finish)
                )

            for s_field, f_field, s_val, f_val in date_errs:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="invalid_date_range",
                        category="data_quality",
                        title=f"Inverted Date Range ({s_field} > {f_field})",
                        severity="high",
                        method="chronological_date_order_verification",
                        limitation=(
                            "Compares start and finish boundaries without calendar adjustments"
                        ),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_code or act.activity_name}' has finish date "
                            f"({f_val}) earlier than start date ({s_val})."
                        ),
                        evidence=[
                            {"field": s_field, "value": str(s_val)},
                            {"field": f_field, "value": str(f_val)},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 5. Check: missing_predecessors (Open Start - Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("missing_predecessors"):
        checks_run.append("missing_predecessors")
        # Set of activities that have at least one valid predecessor within this version
        has_predecessor_ids = {
            rel.successor_activity_id
            for rel in relationships
            if rel.predecessor_activity_id in activity_ids
        }
        for act in activities:
            if act.activity_type in ("start_milestone", "milestone_start"):
                continue  # Start milestones are expected to not have predecessors
            if act.id not in has_predecessor_ids:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="missing_predecessors",
                        category="data_quality",
                        title="Open Start (Missing Predecessors)",
                        severity="medium",
                        method="dependency_graph_inbound_degree_check",
                        limitation=(
                            "Excludes start milestones; does not resolve external interfaces"
                        ),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_code or act.activity_name}' has no inbound "
                            "predecessor dependencies (open start)."
                        ),
                        evidence=[
                            {"field": "activity_id", "value": str(act.id)},
                            {"field": "activity_type", "value": act.activity_type},
                            {"field": "inbound_links_count", "value": 0},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 6. Check: missing_successors (Open Finish - Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("missing_successors"):
        checks_run.append("missing_successors")
        # Set of activities that have at least one valid successor within this version
        has_successor_ids = {
            rel.predecessor_activity_id
            for rel in relationships
            if rel.successor_activity_id in activity_ids
        }
        for act in activities:
            if act.activity_type in ("finish_milestone", "milestone_finish"):
                continue  # Finish milestones are expected to not have successors
            if act.id not in has_successor_ids:
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="missing_successors",
                        category="data_quality",
                        title="Open Finish (Missing Successors)",
                        severity="medium",
                        method="dependency_graph_outbound_degree_check",
                        limitation=(
                            "Excludes finish milestones; does not resolve external interfaces"
                        ),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_code or act.activity_name}' has no outbound "
                            "successor dependencies (open finish)."
                        ),
                        evidence=[
                            {"field": "activity_id", "value": str(act.id)},
                            {"field": "activity_type", "value": act.activity_type},
                            {"field": "outbound_links_count", "value": 0},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 7. Check: invalid_progress (Data Quality)
    # -----------------------------------------------------------------------
    if _should_run("invalid_progress"):
        checks_run.append("invalid_progress")
        for act in activities:
            for pct_field in (
                "physical_pct_complete",
                "duration_pct_complete",
                "units_pct_complete",
            ):
                pct_val = getattr(act, pct_field, None)
                if pct_val is not None:
                    flt_val = float(pct_val)
                    if flt_val < 0.0 or flt_val > 100.0:
                        findings.append(
                            QualityFindingItem(
                                id=uuid.uuid4(),
                                check_code="invalid_progress",
                                category="data_quality",
                                title=f"Progress Percentage Out of Range ({pct_field})",
                                severity="high",
                                method="percentage_bounds_check",
                                limitation=(
                                    "Evaluates 0-100 range bounds without earned value weighting"
                                ),
                                entity_type="activity",
                                entity_id=act.id,
                                entity_source_id=act.source_activity_id,
                                entity_code=act.activity_code,
                                message=(
                                    f"Activity '{act.activity_code or act.activity_name}' has "
                                    f"{pct_field} = {flt_val}%, outside 0-100% range."
                                ),
                                evidence=[
                                    {"field": pct_field, "value": flt_val},
                                ],
                            )
                        )

    # -----------------------------------------------------------------------
    # 8. Check: negative_float (Schedule Performance)
    # -----------------------------------------------------------------------
    if _should_run("negative_float"):
        checks_run.append("negative_float")
        for act in activities:
            if act.total_float_hours is not None and float(act.total_float_hours) < 0.0:
                tf_val = float(act.total_float_hours)
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="negative_float",
                        category="schedule_performance",
                        title=f"Negative Total Float ({tf_val:g}h)",
                        severity="critical",
                        method="imported_source_total_float_negative_threshold",
                        limitation=("Evaluates imported source total float; does not re-run CPM"),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_code or act.activity_name}' has "
                            f"negative total float of {tf_val:g} hours, indicating schedule delay."
                        ),
                        evidence=[
                            {"field": "total_float_hours", "value": tf_val},
                        ],
                    )
                )

    # -----------------------------------------------------------------------
    # 9. Check: high_float (Schedule Performance)
    # -----------------------------------------------------------------------
    if _should_run("high_float"):
        checks_run.append("high_float")
        high_float_threshold = 352.0  # 44 working days @ 8h/day
        for act in activities:
            if (
                act.total_float_hours is not None
                and float(act.total_float_hours) > high_float_threshold
            ):
                tf_val = float(act.total_float_hours)
                findings.append(
                    QualityFindingItem(
                        id=uuid.uuid4(),
                        check_code="high_float",
                        category="schedule_performance",
                        title=f"High Total Float ({tf_val:g}h)",
                        severity="low",
                        method="imported_source_total_float_high_threshold",
                        limitation=(
                            f"Threshold {high_float_threshold:g}h (44 working days); "
                            "indicates possible missing logic or unconstrained end"
                        ),
                        entity_type="activity",
                        entity_id=act.id,
                        entity_source_id=act.source_activity_id,
                        entity_code=act.activity_code,
                        message=(
                            f"Activity '{act.activity_code or act.activity_name}' has "
                            f"high total float ({tf_val:g}h), suggesting loose logic."
                        ),
                        evidence=[
                            {"field": "total_float_hours", "value": tf_val},
                            {"field": "threshold_hours", "value": high_float_threshold},
                        ],
                    )
                )

    # Summary calculation
    data_quality_count = sum(1 for f in findings if f.category == "data_quality")
    schedule_performance_count = sum(1 for f in findings if f.category == "schedule_performance")

    severity_counts: dict[str, int] = {
        "critical": sum(1 for f in findings if f.severity == "critical"),
        "high": sum(1 for f in findings if f.severity == "high"),
        "medium": sum(1 for f in findings if f.severity == "medium"),
        "low": sum(1 for f in findings if f.severity == "low"),
        "info": sum(1 for f in findings if f.severity == "info"),
    }

    summary = QualityCheckSummary(
        total_findings=len(findings),
        data_quality_count=data_quality_count,
        schedule_performance_count=schedule_performance_count,
        by_severity=severity_counts,
        checks_run=checks_run,
    )

    run_id: uuid.UUID | None = None
    if persist:
        # Create AnalysisRun
        analysis_run = AnalysisRun(
            id=uuid.uuid4(),
            workspace_id=project.workspace_id,
            project_id=project.id,
            project_version_id=target_version_id,
            analysis_type="schedule_quality",
            engine_name="pi_schedule_validator",
            engine_version="1.0.0",
            method="deterministic_schedule_audit",
            parameters={"selected_checks": selected_checks},
            result=summary.model_dump(),
            status="completed",
            requested_by=requested_by,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        session.add(analysis_run)
        await session.flush()
        run_id = analysis_run.id

        # Create AnalysisFinding rows
        db_findings = [
            AnalysisFinding(
                id=f.id,
                analysis_run_id=analysis_run.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
                project_version_id=target_version_id,
                finding_code=f.check_code,
                title=f.title,
                description=f.message,
                severity=f.severity,
                entity_type=f.entity_type,
                entity_source_id=f.entity_source_id,
                evidence=f.evidence,
                recommendation={
                    "category": f.category,
                    "method": f.method,
                    "limitation": f.limitation,
                },
            )
            for f in findings
        ]
        session.add_all(db_findings)
        await session.commit()

    return QualityCheckReport(
        project_id=project.id,
        version_id=target_version_id,
        run_id=run_id,
        data_date=version.data_date,
        summary=summary,
        findings=findings,
    )
