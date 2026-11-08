"""Architecture guard: domain code must not import web framework, LLM or parser adapters.

Enforces the rule in 02_SYSTEM_ARCHITECTURE.md section 3 so modules stay separable.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_IN_DOMAINS = ("fastapi", "starlette", "openai", "app.adapters", "app.api")
# Schedule calculations must additionally never see parser or AI code.
FORBIDDEN_IN_SCHEDULE = FORBIDDEN_IN_DOMAINS + ("app.domains.ai", "app.domains.ingestion")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _violations(folder: Path, forbidden: tuple[str, ...]) -> list[str]:
    bad: list[str] = []
    for py in folder.rglob("*.py"):
        for imp in _imports(py):
            if any(imp == f or imp.startswith(f + ".") for f in forbidden):
                bad.append(f"{py.relative_to(APP)} imports {imp}")
    return bad


def test_domains_do_not_depend_on_framework_or_adapters() -> None:
    assert _violations(APP / "domains", FORBIDDEN_IN_DOMAINS) == []


def test_schedule_engine_is_isolated_from_ai_and_ingestion() -> None:
    assert _violations(APP / "domains" / "schedule", FORBIDDEN_IN_SCHEDULE) == []
