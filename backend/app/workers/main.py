"""Background worker entrypoint (placeholder).

Queue technology (RQ/Celery/Arq) is an open decision in 02_SYSTEM_ARCHITECTURE.md and is
deliberately NOT chosen in PI-001. Real job handling arrives with PI-013.
"""

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    structlog.get_logger().info("worker.placeholder", note="no queue backend selected yet")


if __name__ == "__main__":
    main()
