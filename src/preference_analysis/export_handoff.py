"""Export the fitted preference model as a small, tracked teammate handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline

from .inference import (
    RAW_PREDICTION_COLUMNS,
    SUPPORTED_SURVEY_YEARS,
    build_accessibility_category_contract,
    build_deployment_pipeline,
    predict_probability_frame,
    predict_proba_class_order,
)
from .mapping import OTHER_CATEGORY, PREFERENCE_OUTPUT_CATEGORIES
from .modeling import AGE_LABELS, SEX_LABELS


DEFAULT_OUTPUT_DIR = Path("models/preference_analysis/v1")
MODEL_RELATIVE_PATH = Path(
    "data/processed/preference_analysis/model/"
    "multinomial_logistic_2021_2024.joblib"
)
METADATA_RELATIVE_PATH = Path(
    "data/processed/preference_analysis/model/multinomial_model_metadata.json"
)
MAPPING_RELATIVE_PATH = Path(
    "data/processed/preference_analysis/"
    "leisure_activity_middle_category_mapping.csv"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision(project_root: Path, ref: str = "HEAD") -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", ref],
            cwd=project_root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _require_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"필수 handoff 입력 파일이 없습니다: {path}")


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _input_codebook() -> dict[str, Any]:
    return {
        "sex_code": {
            "dtype": "integer",
            "required": True,
            "allowed_values": {str(code): label for code, label in SEX_LABELS.items()},
            "description": "응답자 성별 코드",
        },
        "age_code": {
            "dtype": "integer",
            "required": True,
            "allowed_values": {str(code): label for code, label in AGE_LABELS.items()},
            "description": "15세 이상 연령구간 코드",
        },
        "survey_year": {
            "dtype": "integer",
            "required": True,
            "allowed_values": list(SUPPORTED_SURVEY_YEARS),
            "production_value": 2024,
            "description": "모델 연도효과; 2024 공간 추정에는 2024 사용",
        },
    }


def _example_input() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "example_id": "male_15_19_2024",
                "sex_code": 1,
                "age_code": 1,
                "survey_year": 2024,
            },
            {
                "example_id": "female_20s_2024",
                "sex_code": 2,
                "age_code": 2,
                "survey_year": 2024,
            },
            {
                "example_id": "male_60s_2024",
                "sex_code": 1,
                "age_code": 6,
                "survey_year": 2024,
            },
            {
                "example_id": "female_70plus_2024",
                "sex_code": 2,
                "age_code": 7,
                "survey_year": 2024,
            },
        ]
    )


def export_handoff_package(
    project_root: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    """Create the versioned handoff package from validated local outputs."""

    root = Path(project_root).expanduser().resolve()
    output = Path(output_dir)
    if not output.is_absolute():
        output = root / output
    output.mkdir(parents=True, exist_ok=True)

    source_model_path = root / MODEL_RELATIVE_PATH
    source_metadata_path = root / METADATA_RELATIVE_PATH
    source_mapping_path = root / MAPPING_RELATIVE_PATH
    for path in (source_model_path, source_metadata_path, source_mapping_path):
        _require_file(path)

    fitted_model = joblib.load(source_model_path)
    if not isinstance(fitted_model, Pipeline):
        raise TypeError("학습 모델 Joblib이 sklearn Pipeline이 아닙니다.")
    deployment_pipeline = build_deployment_pipeline(fitted_model)
    class_order = predict_proba_class_order(deployment_pipeline)

    training_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    metadata_classes = tuple(str(value) for value in training_metadata["classes"])
    if class_order != metadata_classes:
        raise ValueError(
            "Joblib predict_proba 클래스 순서와 학습 metadata가 다릅니다: "
            f"joblib={class_order}, metadata={metadata_classes}"
        )

    model_path = output / "preference_model_pipeline.joblib"
    mapping_path = output / "activity_category_mapping.csv"
    access_contract_path = output / "accessibility_category_contract.csv"
    example_input_path = output / "example_input.csv"
    example_output_path = output / "example_output.csv"
    requirements_path = output / "requirements.txt"
    contract_path = output / "model_contract.json"

    joblib.dump(deployment_pipeline, model_path)
    shutil.copyfile(source_mapping_path, mapping_path)
    access_contract = build_accessibility_category_contract()
    _write_csv(access_contract, access_contract_path)

    example_input = _example_input()
    example_output = predict_probability_frame(deployment_pipeline, example_input)
    _write_csv(example_input, example_input_path)
    _write_csv(example_output, example_output_path)
    requirements_path.write_text(
        "\n".join(
            (
                f"numpy=={np.__version__}",
                f"pandas=={pd.__version__}",
                f"scikit-learn=={sklearn.__version__}",
                f"joblib=={joblib.__version__}",
                "",
            )
        ),
        encoding="utf-8",
    )

    class_contract = [
        {
            "class_index": index,
            "middle_category": category,
            "is_policy_category": category in PREFERENCE_OUTPUT_CATEGORIES,
            "is_other_category": category == OTHER_CATEGORY,
        }
        for index, category in enumerate(class_order)
    ]
    contract: dict[str, Any] = {
        "contract_version": "1.0.0",
        "bundle_name": "satisfaction_activity_preference_model_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(root),
        "git_revision_role": (
            "배포 시점의 기준 commit이며, 학습에 사용한 미커밋 코드까지 포함한 "
            "정확한 재현 기준은 training_metadata.code_files SHA-256임"
        ),
        "verified_accessibility_revision": _git_revision(root, "origin/main"),
        "model_artifact": {
            "file": model_path.name,
            "size_bytes": model_path.stat().st_size,
            "sha256": sha256_file(model_path),
            "object_type": "sklearn.pipeline.Pipeline",
            "pipeline_steps": [
                "input_adapter: PreferenceInputTransformer",
                "preference_model: fitted sklearn Pipeline",
            ],
            "preprocessor_access": (
                "pipeline.named_steps['preference_model']"
                ".named_steps['preprocessor']"
            ),
            "classifier_access": (
                "pipeline.named_steps['preference_model']"
                ".named_steps['classifier']"
            ),
        },
        "input_contract": {
            "container": "pandas.DataFrame",
            "raw_columns_in_order": list(RAW_PREDICTION_COLUMNS),
            "extra_columns_allowed": True,
            "derived_columns": {
                "sex_age_code": "str(sex_code) + '_' + str(age_code)"
            },
            "codebook": _input_codebook(),
        },
        "predict_proba_contract": {
            "class_order": class_contract,
            "row_probability_sum": 1.0,
            "meaning": "만족활동 1·2·3순위 기반 경험선호 절대확률",
            "not_actual_usage_probability": True,
        },
        "category_contract": {
            "policy_categories": list(PREFERENCE_OUTPUT_CATEGORIES),
            "other_category": OTHER_CATEGORY,
            "activity_mapping_file": mapping_path.name,
            "accessibility_crosswalk_file": access_contract_path.name,
            "unsupported_accessibility_categories_are_zero": False,
        },
        "accessibility_integration": {
            "latest_verified_output": (
                "notebooks/access/OUTPUT/h3sfca/"
                "h3sfca_격자_중분류_접근성.csv"
            ),
            "accessibility_key": ["접근수단", "GRID_CD", "중분류"],
            "preference_grid_output": (
                "data/processed/preference_analysis/spatial/"
                "grid_middle_category_preference_demand_2024.csv"
            ),
            "preference_key": ["GRID_CD", "middle_category"],
            "category_column_mapping": {"middle_category": "중분류"},
            "h3sfca_demand_column": "potential_demand_absolute",
            "h3sfca_demand_alias": "수요인구수",
            "supported_categories": list(PREFERENCE_OUTPUT_CATEGORIES),
            "unsupported_accessibility_categories": ["음악", "체육용품"],
            "unsupported_value_policy": "NA_not_zero",
            "missing_accessibility_value_policy": (
                "접근성 담당자의 무자료 정의 확인 전 0으로 대체하지 않음"
            ),
            "recalculation_note": (
                "선호 반영 H3SFCA는 potential_demand_absolute를 시설 유효수요 "
                "계산 전에 결합하여 H3SFCA 전체를 재계산해야 함"
            ),
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "source_model": {
            "relative_path": MODEL_RELATIVE_PATH.as_posix(),
            "size_bytes": source_model_path.stat().st_size,
            "sha256": sha256_file(source_model_path),
        },
        "training_metadata": training_metadata,
        "files": {},
    }

    for path in (
        mapping_path,
        access_contract_path,
        example_input_path,
        example_output_path,
        requirements_path,
    ):
        contract["files"][path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    contract_path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the fitted preference model teammate handoff package."
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    contract = export_handoff_package(args.project_root, args.output_dir)
    print(
        "handoff exported: "
        f"classes={len(contract['predict_proba_contract']['class_order'])}, "
        f"model_sha256={contract['model_artifact']['sha256']}"
    )


if __name__ == "__main__":
    main()
