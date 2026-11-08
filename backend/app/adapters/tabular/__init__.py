"""Tabular data adapter package (PI-022)."""

from app.adapters.tabular.reader import (
    TabularInspection,
    inspect_tabular_bytes,
    read_tabular_rows,
)

__all__ = ["TabularInspection", "inspect_tabular_bytes", "read_tabular_rows"]
