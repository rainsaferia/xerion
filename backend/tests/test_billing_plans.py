"""Unit tests for billing domain plan configurations and schemas (PI-050)."""

from app.domains.billing.plans import (
    FREE_PLAN,
    get_plan_definition,
    list_available_plans,
)
from app.domains.billing.schemas import PlanInfo, PlanLimitExceededError, PlanQuotasOut


def test_get_plan_definition_defaults_to_free() -> None:
    plan = get_plan_definition(None)
    assert plan.code == "free"
    assert plan.quotas.max_projects == 2
    assert plan.quotas.max_ai_queries_per_month == 30

    unknown = get_plan_definition("non_existent_tier")
    assert unknown.code == "free"


def test_get_plan_definition_pro_and_enterprise() -> None:
    pro = get_plan_definition("pro")
    assert pro.code == "pro"
    assert pro.quotas.max_projects == 15
    assert pro.quotas.max_ai_queries_per_month == 500

    ent = get_plan_definition("ENTERPRISE")
    assert ent.code == "enterprise"
    assert ent.quotas.max_projects == 1000


def test_list_available_plans() -> None:
    plans = list_available_plans()
    assert len(plans) == 3
    codes = [p.code for p in plans]
    assert "free" in codes
    assert "pro" in codes
    assert "enterprise" in codes


def test_plan_info_pydantic_serialization() -> None:
    info = PlanInfo(
        code=FREE_PLAN.code,
        name=FREE_PLAN.name,
        description=FREE_PLAN.description,
        monthly_price_usd=FREE_PLAN.monthly_price_usd,
        quotas=PlanQuotasOut(
            max_projects=FREE_PLAN.quotas.max_projects,
            max_file_uploads_per_month=FREE_PLAN.quotas.max_file_uploads_per_month,
            max_imports_per_month=FREE_PLAN.quotas.max_imports_per_month,
            max_ai_queries_per_month=FREE_PLAN.quotas.max_ai_queries_per_month,
            max_scenarios_per_month=FREE_PLAN.quotas.max_scenarios_per_month,
            max_reports_per_month=FREE_PLAN.quotas.max_reports_per_month,
            max_upload_size_bytes=FREE_PLAN.quotas.max_upload_size_bytes,
        ),
        features=FREE_PLAN.features,
    )
    dumped = info.model_dump()
    assert dumped["code"] == "free"
    assert dumped["quotas"]["max_projects"] == 2


def test_plan_limit_exceeded_error() -> None:
    err = PlanLimitExceededError(
        metric_name="ai_query",
        current_usage=30.0,
        limit=30.0,
        plan_code="free",
    )
    assert "ai_query" in str(err)
    assert "FREE" in str(err)
    assert err.current_usage == 30.0
    assert err.limit == 30.0
