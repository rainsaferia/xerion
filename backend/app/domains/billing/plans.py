"""Plan tiers, quotas, and feature configurations (PI-050)."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PlanQuotas:
    max_projects: int
    max_file_uploads_per_month: int
    max_imports_per_month: int
    max_ai_queries_per_month: int
    max_scenarios_per_month: int
    max_reports_per_month: int
    max_upload_size_bytes: int


@dataclass(frozen=True)
class PlanDefinition:
    code: str
    name: str
    description: str
    monthly_price_usd: float
    quotas: PlanQuotas
    features: list[str] = field(default_factory=list)


FREE_PLAN = PlanDefinition(
    code="free",
    name="Free Starter",
    description=(
        "Essential schedule viewing and deterministic quality checks "
        "for individual project controllers."
    ),
    monthly_price_usd=0.0,
    quotas=PlanQuotas(
        max_projects=2,
        max_file_uploads_per_month=10,
        max_imports_per_month=5,
        max_ai_queries_per_month=30,
        max_scenarios_per_month=10,
        max_reports_per_month=5,
        max_upload_size_bytes=15 * 1024 * 1024,  # 15 MB
    ),
    features=[
        "2 Active Projects",
        "Primavera P6 XER & Tabular Ingestion",
        "Schedule Quality Checks (DCMA 14-Point Baseline)",
        "30 Project AI Inquiries / Month",
        "10 Delay Scenarios / Month",
        "Standard PDF Schedule Reports",
    ],
)

PRO_PLAN = PlanDefinition(
    code="pro",
    name="Professional EPC",
    description=(
        "Advanced deterministic analytics, version comparisons, "
        "and full AI orchestration for project teams."
    ),
    monthly_price_usd=149.0,
    quotas=PlanQuotas(
        max_projects=15,
        max_file_uploads_per_month=100,
        max_imports_per_month=50,
        max_ai_queries_per_month=500,
        max_scenarios_per_month=100,
        max_reports_per_month=50,
        max_upload_size_bytes=100 * 1024 * 1024,  # 100 MB
    ),
    features=[
        "15 Active Projects with Unlimited Version History",
        "Multi-Version Reconciliation & Reconciliation Diff Dumps",
        "Deterministic Milestone Forecasting & Slippage Analysis",
        "What-If CPM Forward Pass Delay Simulations",
        "500 Project AI Inquiries / Month with Evidence Citations",
        "Excel-friendly CSV & Styled XLSX Exports",
        "Branded Multi-Page PDF Schedule Reports",
    ],
)

ENTERPRISE_PLAN = PlanDefinition(
    code="enterprise",
    name="Enterprise Program",
    description=(
        "Unlimited schedule analytics, custom storage endpoints, "
        "dedicated LLMs, and enterprise SLA."
    ),
    monthly_price_usd=999.0,
    quotas=PlanQuotas(
        max_projects=1000,
        max_file_uploads_per_month=10000,
        max_imports_per_month=5000,
        max_ai_queries_per_month=10000,
        max_scenarios_per_month=5000,
        max_reports_per_month=5000,
        max_upload_size_bytes=500 * 1024 * 1024,  # 500 MB
    ),
    features=[
        "Unlimited Active Projects & Program Workspaces",
        "Custom Private Cloud or On-Premises Storage Adapters",
        "Dedicated Private LLM Provider Endpoints",
        "Custom Schedule Integrity & Governance Rules",
        "Dedicated EPC Project Controls Solutions Architect",
        "99.9% Availability SLA & Priority Audit Logging",
    ],
)

PLANS_BY_CODE: dict[str, PlanDefinition] = {
    "free": FREE_PLAN,
    "pro": PRO_PLAN,
    "enterprise": ENTERPRISE_PLAN,
}


def get_plan_definition(code: str | None) -> PlanDefinition:
    """Retrieve plan definition by code, defaulting to Free Starter."""
    if not code:
        return FREE_PLAN
    return PLANS_BY_CODE.get(code.lower(), FREE_PLAN)


def list_available_plans() -> list[PlanDefinition]:
    """List all available subscription plans."""
    return [FREE_PLAN, PRO_PLAN, ENTERPRISE_PLAN]
