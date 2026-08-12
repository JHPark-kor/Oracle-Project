"""Preference-demand preprocessing and modeling utilities."""

from .mapping import (
    MODEL_CATEGORIES,
    OTHER_CATEGORY,
    POLICY_EXCLUDED_PREFERENCE_CATEGORIES,
    PREFERENCE_OUTPUT_CATEGORIES,
    SATISFACTION_RANK_COLUMNS,
    UNMODELED_PREFERENCE_CATEGORIES,
    build_activity_mapping,
    transform_satisfaction_ranks,
)
from .inference import (
    RAW_PREDICTION_COLUMNS,
    PreferenceInputTransformer,
    build_accessibility_category_contract,
    build_deployment_pipeline,
    build_h3sfca_demand_table,
    load_preference_pipeline,
    merge_preference_with_h3sfca,
    predict_probability_frame,
    predict_proba_class_order,
    prepare_prediction_input,
)
from .modeling import (
    build_sex_age_probability_table,
    evaluate_model,
    fit_multinomial_model,
    prepare_model_frame,
)
from .population_alignment import (
    ALIGNED_POPULATION_COLUMN,
    SOURCE_POPULATION_COLUMN,
    align_grid_sex_age_population,
    validate_preference_probability_cells,
)
from .spatial_demand import (
    aggregate_preference_demand,
    build_all_spatial_demand,
    build_grid_preference_demand,
    build_spatial_validation_summary,
)

__all__ = [
    "MODEL_CATEGORIES",
    "OTHER_CATEGORY",
    "POLICY_EXCLUDED_PREFERENCE_CATEGORIES",
    "PREFERENCE_OUTPUT_CATEGORIES",
    "SATISFACTION_RANK_COLUMNS",
    "UNMODELED_PREFERENCE_CATEGORIES",
    "ALIGNED_POPULATION_COLUMN",
    "SOURCE_POPULATION_COLUMN",
    "RAW_PREDICTION_COLUMNS",
    "PreferenceInputTransformer",
    "align_grid_sex_age_population",
    "aggregate_preference_demand",
    "build_all_spatial_demand",
    "build_activity_mapping",
    "build_accessibility_category_contract",
    "build_deployment_pipeline",
    "build_grid_preference_demand",
    "build_h3sfca_demand_table",
    "build_sex_age_probability_table",
    "build_spatial_validation_summary",
    "evaluate_model",
    "fit_multinomial_model",
    "load_preference_pipeline",
    "merge_preference_with_h3sfca",
    "predict_probability_frame",
    "predict_proba_class_order",
    "prepare_model_frame",
    "prepare_prediction_input",
    "transform_satisfaction_ranks",
    "validate_preference_probability_cells",
]
