from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_BACKENDS = {"local", "oracle"}
SUPPORTED_OCI_AUTH = {"api_key", "security_token"}
REQUIRED_WALLET_FILES = (
    "tnsnames.ora",
    "sqlnet.ora",
    "ewallet.pem",
    "cwallet.sso",
)


@dataclass(frozen=True)
class OciSettings:
    """Non-secret OCI resource names and local connection settings."""

    data_backend: str
    config_file: Path
    profile: str
    auth: str
    region: str
    compartment_name: str
    raw_bucket: str
    artifact_bucket: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "OciSettings":
        env = os.environ if environ is None else environ
        return cls(
            data_backend=env.get("DATA_BACKEND", "local").strip().lower(),
            config_file=Path(env.get("OCI_CONFIG_FILE", "~/.oci/config")).expanduser(),
            profile=env.get("OCI_PROFILE", "MNC_SETUP").strip(),
            auth=env.get("OCI_AUTH", "security_token").strip().lower(),
            region=env.get("OCI_REGION", "ap-tokyo-1").strip(),
            compartment_name=env.get(
                "OCI_COMPARTMENT_NAME", "mnc-project-dev"
            ).strip(),
            raw_bucket=env.get("OCI_RAW_BUCKET", "mnc-raw-private").strip(),
            artifact_bucket=env.get(
                "OCI_ARTIFACT_BUCKET", "mnc-artifacts"
            ).strip(),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if self.data_backend not in SUPPORTED_BACKENDS:
            errors.append(
                "DATA_BACKEND는 local 또는 oracle이어야 합니다: "
                f"{self.data_backend!r}"
            )
        if self.auth not in SUPPORTED_OCI_AUTH:
            errors.append(
                "OCI_AUTH는 api_key 또는 security_token이어야 합니다: "
                f"{self.auth!r}"
            )
        for field_name, value in (
            ("OCI_PROFILE", self.profile),
            ("OCI_REGION", self.region),
            ("OCI_COMPARTMENT_NAME", self.compartment_name),
            ("OCI_RAW_BUCKET", self.raw_bucket),
            ("OCI_ARTIFACT_BUCKET", self.artifact_bucket),
        ):
            if not value:
                errors.append(f"{field_name} 값이 비어 있습니다.")
        return errors


@dataclass(frozen=True)
class OracleDbSettings:
    """Non-secret Oracle Database connection settings.

    Passwords are intentionally excluded. Callers must obtain the database and
    wallet passwords at runtime or from an approved secret manager.
    """

    user: str
    dsn: str
    wallet_dir: Path | None

    @classmethod
    def from_env(
        cls, environ: Mapping[str, str] | None = None
    ) -> "OracleDbSettings":
        env = os.environ if environ is None else environ
        wallet_value = env.get("ORACLE_DB_WALLET_DIR", "").strip()
        return cls(
            user=env.get("ORACLE_DB_USER", "ADMIN").strip().upper(),
            dsn=env.get("ORACLE_DB_DSN", "mncdev_low").strip(),
            wallet_dir=(
                Path(wallet_value).expanduser() if wallet_value else None
            ),
        )

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.user:
            errors.append("ORACLE_DB_USER 값이 비어 있습니다.")
        if not self.dsn:
            errors.append("ORACLE_DB_DSN 값이 비어 있습니다.")
        if self.wallet_dir is None:
            errors.append("ORACLE_DB_WALLET_DIR 값이 비어 있습니다.")
            return errors
        if not self.wallet_dir.is_dir():
            errors.append(
                f"Wallet 폴더를 찾을 수 없습니다: {self.wallet_dir}"
            )
            return errors
        for filename in REQUIRED_WALLET_FILES:
            path = self.wallet_dir / filename
            if not path.is_file() or path.stat().st_size == 0:
                errors.append(f"Wallet 필수 파일이 없습니다: {path}")
        return errors
