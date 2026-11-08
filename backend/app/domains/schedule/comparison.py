"""Deterministic schedule version comparison engine (PI-034).

Rules (02_SYSTEM_ARCHITECTURE.md, 08_DEVELOPMENT_BACKLOG.md):
- Matching rule: Stable P6 source ID first, activity code second.
  Never match solely on activity name.
- Ambiguous matches (duplicate codes in either version) must be isolated into 'ambiguous' category.
- Exact count reconciliation:
  from_version_total == matched + removed + ambiguous_from
  to_version_total == matched + added + ambiguous_to
  matched == changed + unchanged
- Diffs identify added, removed, changed, unchanged, ambiguous activities.
- Domain isolation: zero dependencies on FastAPI, HTTP, AI, or Ingestion.
"""

import csv
import io
import uuid
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.schedule.schemas import (
    ActivityDiffItem,
    ComparisonSummary,
    DiffCategory,
    FieldDiff,
    RelationshipDiff,
    VersionComparisonReport,
)
from app.models.project import ProjectVersion
from app.models.schedule import Activity, ActivityRelationship

COMPARED_FIELDS = (
    "activity_name",
    "status",
    "planned_start",
    "planned_finish",
    "start_date",
    "finish_date",
    "actual_start",
    "actual_finish",
    "original_duration_hours",
    "remaining_duration_hours",
    "actual_duration_hours",
    "total_float_hours",
    "free_float_hours",
    "physical_pct_complete",
    "duration_pct_complete",
    "units_pct_complete",
)


def _to_json_val(val: Any) -> Any:
    """Normalize decimal or date values to standard types for diff items."""
    if isinstance(val, Decimal):
        return float(val)
    return val


def _calculate_delta(old_val: Any, new_val: Any) -> Any | None:
    """Calculate delta between two values if types are compatible."""
    if old_val is None or new_val is None:
        return None

    if isinstance(old_val, date) and isinstance(new_val, date):
        return (new_val - old_val).days

    try:
        old_num = float(old_val)
        new_num = float(new_val)
        return round(new_num - old_num, 4)
    except (ValueError, TypeError):
        return None


def _is_field_changed(old_val: Any, new_val: Any) -> bool:
    """Determine whether a field value meaningfully changed."""
    if old_val is None and new_val is None:
        return False
    if old_val is None or new_val is None:
        return True

    # Numeric float/decimal comparison with epsilon
    try:
        old_num = float(old_val)
        new_num = float(new_val)
        return abs(old_num - new_num) > 1e-4
    except (ValueError, TypeError):
        pass

    return bool(old_val != new_val)


async def compare_versions(
    session: AsyncSession,
    project_id: uuid.UUID,
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    fields: list[str] | None = None,
    category_filter: DiffCategory | None = None,
    limit: int = 100,
    offset: int = 0,
) -> VersionComparisonReport:
    """Deterministic comparison between two confirmed schedule versions."""
    # 1. Fetch versions metadata
    v_query = select(ProjectVersion).where(
        ProjectVersion.project_id == project_id,
        ProjectVersion.id.in_([from_version_id, to_version_id]),
    )
    v_res = await session.execute(v_query)
    versions = {v.id: v for v in v_res.scalars().all()}

    from_v = versions.get(from_version_id)
    to_v = versions.get(to_version_id)

    if not from_v or not to_v:
        raise ValueError(f"One or both versions not found for project {project_id}")

    # 2. Fetch all activities for both versions
    acts_a_res = await session.execute(
        select(Activity)
        .where(Activity.project_version_id == from_version_id)
        .order_by(Activity.activity_code, Activity.source_activity_id)
    )
    acts_a: list[Activity] = list(acts_a_res.scalars().all())

    acts_b_res = await session.execute(
        select(Activity)
        .where(Activity.project_version_id == to_version_id)
        .order_by(Activity.activity_code, Activity.source_activity_id)
    )
    acts_b: list[Activity] = list(acts_b_res.scalars().all())

    # 3. Fetch relationships for both versions
    rels_a_res = await session.execute(
        select(ActivityRelationship).where(
            ActivityRelationship.project_version_id == from_version_id
        )
    )
    rels_a = list(rels_a_res.scalars().all())

    rels_b_res = await session.execute(
        select(ActivityRelationship).where(ActivityRelationship.project_version_id == to_version_id)
    )
    rels_b = list(rels_b_res.scalars().all())

    # Map activities by ID within their respective versions
    act_a_by_id = {a.id: a for a in acts_a}
    act_b_by_id = {b.id: b for b in acts_b}

    # 4. Detect duplicate activity codes (ambiguity detection)
    codes_a = [a.activity_code for a in acts_a if a.activity_code]
    counter_a = Counter(codes_a)
    ambiguous_codes_a = {c for c, count in counter_a.items() if count > 1}

    codes_b = [b.activity_code for b in acts_b if b.activity_code]
    counter_b = Counter(codes_b)
    ambiguous_codes_b = {c for c, count in counter_b.items() if count > 1}

    # 5. Matching algorithm:
    # Stage 1: Match by stable source_activity_id
    matched_pairs: list[tuple[Activity, Activity, str]] = []
    matched_a_ids: set[uuid.UUID] = set()
    matched_b_ids: set[uuid.UUID] = set()

    acts_b_by_source: dict[str, Activity] = {
        b.source_activity_id: b for b in acts_b if b.source_activity_id
    }
    for a in acts_a:
        if a.source_activity_id and a.source_activity_id in acts_b_by_source:
            b = acts_b_by_source[a.source_activity_id]
            matched_pairs.append((a, b, f"source_id:{a.source_activity_id}"))
            matched_a_ids.add(a.id)
            matched_b_ids.add(b.id)

    # Stage 2: Match remaining activities by activity_code
    unmatched_a_stage1 = [a for a in acts_a if a.id not in matched_a_ids]
    unmatched_b_stage1 = [b for b in acts_b if b.id not in matched_b_ids]

    # Activities with non-unique codes in either version cannot be matched safely by code
    b_by_code: dict[str, list[Activity]] = defaultdict(list)
    for b in unmatched_b_stage1:
        if b.activity_code:
            b_by_code[b.activity_code].append(b)

    for a in unmatched_a_stage1:
        if not a.activity_code:
            continue
        # Skip if code is ambiguous in either version
        if a.activity_code in ambiguous_codes_a or a.activity_code in ambiguous_codes_b:
            continue
        candidates_in_b = b_by_code.get(a.activity_code, [])
        if len(candidates_in_b) == 1:
            b = candidates_in_b[0]
            if b.id not in matched_b_ids:
                matched_pairs.append((a, b, f"activity_code:{a.activity_code}"))
                matched_a_ids.add(a.id)
                matched_b_ids.add(b.id)

    # 6. Build relationship maps for diffing
    # Map activity_id -> list of predecessors (other_act_key, type, lag, other_code, other_name)
    def _build_activity_rel_maps(
        rels: list[ActivityRelationship], act_map: dict[uuid.UUID, Activity]
    ) -> tuple[
        dict[uuid.UUID, dict[str, tuple[str, float, str | None, str]]],
        dict[uuid.UUID, dict[str, tuple[str, float, str | None, str]]],
    ]:
        preds_by_act: dict[uuid.UUID, dict[str, tuple[str, float, str | None, str]]] = defaultdict(
            dict
        )
        succs_by_act: dict[uuid.UUID, dict[str, tuple[str, float, str | None, str]]] = defaultdict(
            dict
        )

        for r in rels:
            p = act_map.get(r.predecessor_activity_id)
            s = act_map.get(r.successor_activity_id)
            if not p or not s:
                continue

            p_key = p.source_activity_id or p.activity_code or str(p.id)
            s_key = s.source_activity_id or s.activity_code or str(s.id)
            lag = float(r.lag_hours) if r.lag_hours is not None else 0.0

            # For successor s: predecessor is p
            preds_by_act[s.id][p_key] = (r.relationship_type, lag, p.activity_code, p.activity_name)
            # For predecessor p: successor is s
            succs_by_act[p.id][s_key] = (r.relationship_type, lag, s.activity_code, s.activity_name)

        return preds_by_act, succs_by_act

    preds_a, succs_a = _build_activity_rel_maps(rels_a, act_a_by_id)
    preds_b, succs_b = _build_activity_rel_maps(rels_b, act_b_by_id)

    # 7. Generate diff items
    all_items: list[ActivityDiffItem] = []
    active_fields = fields or COMPARED_FIELDS

    # Matched items
    changed_count = 0
    unchanged_count = 0

    for a, b, match_key in matched_pairs:
        field_changes: list[FieldDiff] = []
        for f in active_fields:
            old_val = getattr(a, f, None)
            new_val = getattr(b, f, None)
            if _is_field_changed(old_val, new_val):
                delta = _calculate_delta(old_val, new_val)
                field_changes.append(
                    FieldDiff(
                        field_name=f,
                        old_value=_to_json_val(old_val),
                        new_value=_to_json_val(new_val),
                        delta=delta,
                    )
                )

        rel_changes: list[RelationshipDiff] = []

        # Compare predecessors
        p_a = preds_a.get(a.id, {})
        p_b = preds_b.get(b.id, {})
        all_pred_keys = set(p_a.keys()) | set(p_b.keys())
        for k in all_pred_keys:
            in_a = k in p_a
            in_b = k in p_b
            if in_a and not in_b:
                rel_type, lag, code, name = p_a[k]
                rel_changes.append(
                    RelationshipDiff(
                        direction="predecessor",
                        relationship_type=rel_type,
                        other_activity_code=code,
                        other_activity_name=name,
                        change_type="removed",
                        old_lag_hours=lag,
                        new_lag_hours=None,
                    )
                )
            elif not in_a and in_b:
                rel_type, lag, code, name = p_b[k]
                rel_changes.append(
                    RelationshipDiff(
                        direction="predecessor",
                        relationship_type=rel_type,
                        other_activity_code=code,
                        other_activity_name=name,
                        change_type="added",
                        old_lag_hours=None,
                        new_lag_hours=lag,
                    )
                )
            else:
                rel_type_a, lag_a, code_a, name_a = p_a[k]
                rel_type_b, lag_b, code_b, name_b = p_b[k]
                if rel_type_a != rel_type_b or abs(lag_a - lag_b) > 1e-4:
                    rel_changes.append(
                        RelationshipDiff(
                            direction="predecessor",
                            relationship_type=rel_type_b,
                            other_activity_code=code_b or code_a,
                            other_activity_name=name_b or name_a,
                            change_type="modified",
                            old_lag_hours=lag_a,
                            new_lag_hours=lag_b,
                        )
                    )

        # Compare successors
        s_a = succs_a.get(a.id, {})
        s_b = succs_b.get(b.id, {})
        all_succ_keys = set(s_a.keys()) | set(s_b.keys())
        for k in all_succ_keys:
            in_a = k in s_a
            in_b = k in s_b
            if in_a and not in_b:
                rel_type, lag, code, name = s_a[k]
                rel_changes.append(
                    RelationshipDiff(
                        direction="successor",
                        relationship_type=rel_type,
                        other_activity_code=code,
                        other_activity_name=name,
                        change_type="removed",
                        old_lag_hours=lag,
                        new_lag_hours=None,
                    )
                )
            elif not in_a and in_b:
                rel_type, lag, code, name = s_b[k]
                rel_changes.append(
                    RelationshipDiff(
                        direction="successor",
                        relationship_type=rel_type,
                        other_activity_code=code,
                        other_activity_name=name,
                        change_type="added",
                        old_lag_hours=None,
                        new_lag_hours=lag,
                    )
                )
            else:
                rel_type_a, lag_a, code_a, name_a = s_a[k]
                rel_type_b, lag_b, code_b, name_b = s_b[k]
                if rel_type_a != rel_type_b or abs(lag_a - lag_b) > 1e-4:
                    rel_changes.append(
                        RelationshipDiff(
                            direction="successor",
                            relationship_type=rel_type_b,
                            other_activity_code=code_b or code_a,
                            other_activity_name=name_b or name_a,
                            change_type="modified",
                            old_lag_hours=lag_a,
                            new_lag_hours=lag_b,
                        )
                    )

        category: DiffCategory = "changed" if (field_changes or rel_changes) else "unchanged"
        if category == "changed":
            changed_count += 1
        else:
            unchanged_count += 1

        all_items.append(
            ActivityDiffItem(
                diff_category=category,
                activity_code=b.activity_code or a.activity_code,
                activity_name=b.activity_name,
                source_activity_id=b.source_activity_id or a.source_activity_id,
                match_key=match_key,
                from_activity_id=a.id,
                to_activity_id=b.id,
                field_changes=field_changes,
                relationship_changes=rel_changes,
            )
        )

    # 8. Unmatched activities in A (Removed or Ambiguous)
    removed_items: list[ActivityDiffItem] = []
    ambiguous_from_count = 0

    for a in acts_a:
        if a.id in matched_a_ids:
            continue
        is_ambiguous = (
            a.activity_code in ambiguous_codes_a
            or (a.activity_code and a.activity_code in ambiguous_codes_b)
            or (
                a.activity_code
                and any(
                    b.activity_code == a.activity_code for b in acts_b if b.id not in matched_b_ids
                )
            )
        )
        if is_ambiguous:
            ambiguous_from_count += 1
            all_items.append(
                ActivityDiffItem(
                    diff_category="ambiguous",
                    activity_code=a.activity_code,
                    activity_name=a.activity_name,
                    source_activity_id=a.source_activity_id,
                    match_key=f"ambiguous_from:{a.activity_code or a.source_activity_id}",
                    from_activity_id=a.id,
                    to_activity_id=None,
                    ambiguous_reason=(
                        "Duplicate or conflicting activity code in baseline/from version"
                    ),
                )
            )
        else:
            removed_items.append(
                ActivityDiffItem(
                    diff_category="removed",
                    activity_code=a.activity_code,
                    activity_name=a.activity_name,
                    source_activity_id=a.source_activity_id,
                    match_key=f"removed:{a.source_activity_id or a.activity_code}",
                    from_activity_id=a.id,
                    to_activity_id=None,
                )
            )

    all_items.extend(removed_items)

    # 9. Unmatched activities in B (Added or Ambiguous)
    added_items: list[ActivityDiffItem] = []
    ambiguous_to_count = 0

    for b in acts_b:
        if b.id in matched_b_ids:
            continue
        is_ambiguous = (
            b.activity_code in ambiguous_codes_b
            or (b.activity_code and b.activity_code in ambiguous_codes_a)
            or (
                b.activity_code
                and any(
                    a.activity_code == b.activity_code for a in acts_a if a.id not in matched_a_ids
                )
            )
        )
        if is_ambiguous:
            ambiguous_to_count += 1
            all_items.append(
                ActivityDiffItem(
                    diff_category="ambiguous",
                    activity_code=b.activity_code,
                    activity_name=b.activity_name,
                    source_activity_id=b.source_activity_id,
                    match_key=f"ambiguous_to:{b.activity_code or b.source_activity_id}",
                    from_activity_id=None,
                    to_activity_id=b.id,
                    ambiguous_reason="Duplicate or conflicting activity code in target/to version",
                )
            )
        else:
            added_items.append(
                ActivityDiffItem(
                    diff_category="added",
                    activity_code=b.activity_code,
                    activity_name=b.activity_name,
                    source_activity_id=b.source_activity_id,
                    match_key=f"added:{b.source_activity_id or b.activity_code}",
                    from_activity_id=None,
                    to_activity_id=b.id,
                )
            )

    all_items.extend(added_items)

    total_ambiguous = ambiguous_from_count + ambiguous_to_count
    total_matched = len(matched_pairs)

    summary = ComparisonSummary(
        from_version_total=len(acts_a),
        to_version_total=len(acts_b),
        matched=total_matched,
        added=len(added_items),
        removed=len(removed_items),
        changed=changed_count,
        unchanged=unchanged_count,
        ambiguous=total_ambiguous,
        change_categories={
            "added": len(added_items),
            "removed": len(removed_items),
            "changed": changed_count,
            "unchanged": unchanged_count,
            "ambiguous": total_ambiguous,
        },
    )

    # 10. Filter and sort items
    category_order: dict[DiffCategory, int] = {
        "changed": 0,
        "added": 1,
        "removed": 2,
        "ambiguous": 3,
        "unchanged": 4,
    }

    filtered_items = all_items
    if category_filter:
        filtered_items = [i for i in all_items if i.diff_category == category_filter]

    filtered_items.sort(
        key=lambda i: (
            category_order.get(i.diff_category, 99),
            i.activity_code or "",
            i.match_key,
        )
    )

    total_count = len(filtered_items)
    paginated_items = filtered_items[offset : offset + limit]

    return VersionComparisonReport(
        project_id=project_id,
        from_version_id=from_version_id,
        to_version_id=to_version_id,
        from_version_number=from_v.version_number,
        to_version_number=to_v.version_number,
        from_data_date=from_v.data_date,
        to_data_date=to_v.data_date,
        summary=summary,
        items=paginated_items,
        total_items=total_count,
        limit=limit,
        offset=offset,
    )


def export_comparison_csv(report: VersionComparisonReport) -> str:
    """Generate RFC 4180 CSV export of version comparison diffs."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "diff_category",
            "activity_code",
            "activity_name",
            "source_activity_id",
            "match_key",
            "field_name",
            "old_value",
            "new_value",
            "delta",
            "ambiguous_reason",
        ]
    )

    for item in report.items:
        if item.field_changes:
            for fc in item.field_changes:
                writer.writerow(
                    [
                        item.diff_category,
                        item.activity_code or "",
                        item.activity_name,
                        item.source_activity_id or "",
                        item.match_key,
                        fc.field_name,
                        str(fc.old_value) if fc.old_value is not None else "",
                        str(fc.new_value) if fc.new_value is not None else "",
                        str(fc.delta) if fc.delta is not None else "",
                        item.ambiguous_reason or "",
                    ]
                )
        elif item.relationship_changes:
            for rc in item.relationship_changes:
                old_desc = f"lag={rc.old_lag_hours}h" if rc.old_lag_hours is not None else ""
                new_desc = (
                    f"lag={rc.new_lag_hours}h ({rc.change_type})"
                    if rc.new_lag_hours is not None
                    else rc.change_type
                )
                writer.writerow(
                    [
                        item.diff_category,
                        item.activity_code or "",
                        item.activity_name,
                        item.source_activity_id or "",
                        item.match_key,
                        f"relationship_{rc.direction}_{rc.relationship_type}",
                        old_desc,
                        new_desc,
                        "",
                        item.ambiguous_reason or "",
                    ]
                )
        else:
            writer.writerow(
                [
                    item.diff_category,
                    item.activity_code or "",
                    item.activity_name,
                    item.source_activity_id or "",
                    item.match_key,
                    "",
                    "",
                    "",
                    "",
                    item.ambiguous_reason or "",
                ]
            )

    return output.getvalue()
