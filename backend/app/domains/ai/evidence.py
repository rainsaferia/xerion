"""Deterministic Evidence Builder (PI-042).

Rules (02_SYSTEM_ARCHITECTURE.md, 05_AI_AGENT_SPEC.md):
- Implements Section 7 Evidence Contract of 05_AI_AGENT_SPEC.md.
- Extracts structured, verifiable evidence references from deterministic tool results.
- Citations follow standard format: [EV: <entity> <field>=<val>].
- Hexagonal domain isolation: zero web framework (fastapi) or vendor adapter dependencies.
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceReference(BaseModel):
    """Normalized evidence record linking finding to source data or calculation (PI-042)."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=lambda: f"ev_{uuid.uuid4().hex[:8]}")
    project_version_id: uuid.UUID
    entity_type: str
    entity_platform_id: str | None = None
    source_identifier: str | None = None
    field_name: str
    source_value: Any | None = None
    normalized_value: Any | None = None
    unit: str | None = None
    method: str = "source_import"
    citation_label: str


def _clean_str(val: Any) -> str:
    return str(val) if val is not None else ""


def build_tool_evidence(
    tool_name: str,
    version_id: uuid.UUID,
    data: dict[str, Any],
) -> list[EvidenceReference]:
    """Extract structured evidence references from deterministic schedule tool outputs."""
    if not isinstance(data, dict) or "error" in data:
        return []

    evidence: list[EvidenceReference] = []

    if tool_name == "get_project_overview":
        if "total_activities" in data:
            val = data["total_activities"]
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="project_kpi",
                    field_name="total_activities",
                    source_value=val,
                    normalized_value=val,
                    unit="count",
                    method="schedule_activity_aggregation",
                    citation_label=f"[EV: total_activities={val}]",
                )
            )
        if "activity_status_counts" in data and isinstance(data["activity_status_counts"], dict):
            for st, cnt in data["activity_status_counts"].items():
                evidence.append(
                    EvidenceReference(
                        project_version_id=version_id,
                        entity_type="project_kpi",
                        field_name=f"status_count_{st}",
                        source_value=cnt,
                        normalized_value=cnt,
                        unit="count",
                        method="status_aggregation",
                        citation_label=f"[EV: status_{st}={cnt}]",
                    )
                )
        if "data_date" in data and data["data_date"]:
            dd = _clean_str(data["data_date"])
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="project_kpi",
                    field_name="data_date",
                    source_value=dd,
                    normalized_value=dd,
                    unit="date",
                    method="source_import",
                    citation_label=f"[EV: data_date={dd}]",
                )
            )
        if "project_start_date" in data and data["project_start_date"]:
            ps = _clean_str(data["project_start_date"])
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="project_kpi",
                    field_name="project_start_date",
                    source_value=ps,
                    normalized_value=ps,
                    unit="date",
                    method="source_import",
                    citation_label=f"[EV: project_start_date={ps}]",
                )
            )
        if "project_finish_date" in data and data["project_finish_date"]:
            pf = _clean_str(data["project_finish_date"])
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="project_kpi",
                    field_name="project_finish_date",
                    source_value=pf,
                    normalized_value=pf,
                    unit="date",
                    method="source_import",
                    citation_label=f"[EV: project_finish_date={pf}]",
                )
            )

    elif tool_name == "get_critical_activities":
        items = data.get("items", [])
        for act in items:
            act_code = _clean_str(act.get("activity_code"))
            tf = act.get("total_float_hours")
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="activity",
                    entity_platform_id=_clean_str(act.get("activity_id")) or None,
                    source_identifier=act_code,
                    field_name="total_float_hours",
                    source_value=tf,
                    normalized_value=tf,
                    unit="hours",
                    method="critical_path_total_float",
                    citation_label=f"[EV: {act_code} total_float_hours={tf}h]",
                )
            )

    elif tool_name == "get_activity_detail":
        act_code = _clean_str(data.get("activity_code"))
        act_id = _clean_str(data.get("activity_id")) or None

        if "total_float_hours" in data and data["total_float_hours"] is not None:
            tf = data["total_float_hours"]
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="activity",
                    entity_platform_id=act_id,
                    source_identifier=act_code,
                    field_name="total_float_hours",
                    source_value=tf,
                    normalized_value=tf,
                    unit="hours",
                    method="cpm_float_calculation",
                    citation_label=f"[EV: {act_code} total_float_hours={tf}h]",
                )
            )

        if "finish_date" in data and data["finish_date"]:
            fd = _clean_str(data["finish_date"])
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="activity",
                    entity_platform_id=act_id,
                    source_identifier=act_code,
                    field_name="finish_date",
                    source_value=fd,
                    normalized_value=fd,
                    unit="date",
                    method="cpm_early_late_dates",
                    citation_label=f"[EV: {act_code} finish_date={fd}]",
                )
            )

        if "baselines" in data and isinstance(data["baselines"], list):
            for bl in data["baselines"]:
                bf = _clean_str(bl.get("baseline_finish"))
                if bf:
                    evidence.append(
                        EvidenceReference(
                            project_version_id=version_id,
                            entity_type="baseline",
                            entity_platform_id=act_id,
                            source_identifier=act_code,
                            field_name="baseline_finish",
                            source_value=bf,
                            normalized_value=bf,
                            unit="date",
                            method="baseline_import",
                            citation_label=f"[EV: {act_code} baseline_finish={bf}]",
                        )
                    )

    elif tool_name == "list_activities":
        items = data.get("items", [])
        for act in items[:10]:  # limit references to top 10 to keep context concise
            act_code = _clean_str(act.get("activity_code"))
            tf = act.get("total_float_hours")
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="activity",
                    entity_platform_id=_clean_str(act.get("id")) or None,
                    source_identifier=act_code,
                    field_name="total_float_hours",
                    source_value=tf,
                    normalized_value=tf,
                    unit="hours",
                    method="cpm_float",
                    citation_label=f"[EV: {act_code} float={tf}h]",
                )
            )

    elif tool_name == "get_float_distribution":
        if "total_activities" in data:
            tot = data["total_activities"]
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="float_distribution",
                    field_name="total_activities",
                    source_value=tot,
                    normalized_value=tot,
                    unit="count",
                    method="float_histogram_aggregation",
                    citation_label=f"[EV: float_activities_total={tot}]",
                )
            )

    elif tool_name == "analyze_schedule_quality":
        findings = data.get("findings", [])
        for f in findings:
            chk_code = _clean_str(f.get("check_code"))
            vc = f.get("violation_count", 0)
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="quality_finding",
                    source_identifier=chk_code,
                    field_name="violation_count",
                    source_value=vc,
                    normalized_value=vc,
                    unit="count",
                    method="deterministic_schedule_check",
                    citation_label=f"[EV: {chk_code} violations={vc}]",
                )
            )

    elif tool_name == "compare_project_versions":
        items = data.get("items", [])
        for diff in items:
            act_code = _clean_str(diff.get("activity_code"))
            f_changes = diff.get("field_changes", [])
            for fc in f_changes:
                fn = _clean_str(fc.get("field_name"))
                delta = fc.get("delta")
                if delta is not None:
                    evidence.append(
                        EvidenceReference(
                            project_version_id=version_id,
                            entity_type="version_diff",
                            source_identifier=act_code,
                            field_name=f"{fn}_delta",
                            source_value=delta,
                            normalized_value=delta,
                            unit="hours" if "hours" in fn else "value",
                            method="version_reconciliation_delta",
                            citation_label=f"[EV: {act_code} {fn} delta={delta}h]",
                        )
                    )

    elif tool_name == "get_milestone_forecast":
        items = data.get("items", [])
        method = _clean_str(data.get("method"))
        for item in items[:15]:
            act_code = _clean_str(item.get("activity_code") or item.get("source_activity_id"))
            proj_date = item.get("projected_date")
            src_date = item.get("source_date")
            tf = item.get("total_float_hours")
            is_calc = item.get("is_calculated_projection", False)
            if proj_date:
                evidence.append(
                    EvidenceReference(
                        project_version_id=version_id,
                        entity_type="milestone_forecast",
                        entity_platform_id=_clean_str(item.get("activity_id")) or None,
                        source_identifier=act_code,
                        field_name="projected_date",
                        source_value=src_date,
                        normalized_value=proj_date,
                        unit="date",
                        method=method,
                        citation_label=(
                            f"[EV: {act_code} forecast={proj_date} (calc)]"
                            if is_calc
                            else f"[EV: {act_code} forecast={proj_date} (imported)]"
                        ),
                    )
                )
            if tf is not None:
                evidence.append(
                    EvidenceReference(
                        project_version_id=version_id,
                        entity_type="milestone_forecast",
                        entity_platform_id=_clean_str(item.get("activity_id")) or None,
                        source_identifier=act_code,
                        field_name="total_float_hours",
                        source_value=tf,
                        normalized_value=tf,
                        unit="hours",
                        method=method,
                        citation_label=f"[EV: {act_code} float={tf}h]",
                    )
                )

    elif tool_name == "simulate_activity_delay":
        items = data.get("affected_items", [])
        for item in items[:15]:
            act_code = _clean_str(item.get("activity_code") or item.get("source_activity_id"))
            scen_finish = item.get("scenario_finish_date")
            src_finish = item.get("source_finish_date")
            delay_w = item.get("delay_working_days")
            if scen_finish and delay_w is not None:
                evidence.append(
                    EvidenceReference(
                        project_version_id=version_id,
                        entity_type="scenario_activity",
                        entity_platform_id=_clean_str(item.get("activity_id")) or None,
                        source_identifier=act_code,
                        field_name="scenario_finish_date",
                        source_value=src_finish,
                        normalized_value=scen_finish,
                        unit="date",
                        method="bounded_cpm_forward_pass",
                        citation_label=(
                            f"[EV: {act_code} scenario_finish={scen_finish} (+{delay_w}d)]"
                        ),
                    )
                )

    elif tool_name == "generate_schedule_report":
        report_id = _clean_str(data.get("id"))
        status = _clean_str(data.get("status"))
        fmt = _clean_str(data.get("output_format"))
        if report_id:
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="report_artifact",
                    entity_platform_id=report_id,
                    source_identifier=report_id,
                    field_name="status",
                    source_value=status,
                    normalized_value=status,
                    unit="status",
                    method="reportlab_deterministic_pdf",
                    citation_label=f"[EV: report/{report_id} status={status} format={fmt}]",
                )
            )

    elif tool_name == "export_activity_data":
        report_id = _clean_str(data.get("id"))
        status = _clean_str(data.get("status"))
        fmt = _clean_str(data.get("output_format"))
        if report_id:
            evidence.append(
                EvidenceReference(
                    project_version_id=version_id,
                    entity_type="export_artifact",
                    entity_platform_id=report_id,
                    source_identifier=report_id,
                    field_name="status",
                    source_value=status,
                    normalized_value=status,
                    unit="status",
                    method=f"tabular_{fmt}_export",
                    citation_label=f"[EV: export/{report_id} status={status} format={fmt}]",
                )
            )

    return evidence
