"""Shared local and Oracle data-access configuration."""

from .oci_config import OciSettings, OracleDbSettings
from .oracle_schema import APP_SCHEMA, ETL_ROLE, READ_ROLE

__all__ = [
    "APP_SCHEMA",
    "ETL_ROLE",
    "OciSettings",
    "OracleDbSettings",
    "READ_ROLE",
]
