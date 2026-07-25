"""Configuration: the grading rules as versioned, validated data.

Changing a threshold must never require changing Python (ARCHITECTURE.md §4.2).
This package turns YAML into frozen, fully typed objects and refuses anything
that would produce a plausible wrong grade — no dictionary escapes it, and every
invariant in ``MODEL_SPEC.md`` §19 is a load failure rather than a warning.

Delivered by GM-003. GM-004 adds the semantic ``config_hash``, versioned
configuration records, a read-only version registry, and a modified-after-use
integrity seal. Bucket resolution, grading, and signal evaluation are Sprint 2.
"""

from __future__ import annotations

from .errors import (
    ConfigIntegrityError,
    ConfigParseError,
    ConfigSchemaError,
    ConfigSemanticError,
    ConfigVersionError,
    ConflictingConfigVersionError,
    DuplicateConfigVersionError,
    MalformedConfigHashError,
    ModifiedAfterUseError,
    SourceModifiedError,
    SourceUnavailableError,
    UnknownConfigVersionError,
    VersionLabelReplacedError,
)
from .hashing import ConfigHash, config_hash, semantic_projection, source_digest
from .loader import StrictConfigLoader, load_config, load_config_text
from .schema import (
    AllocationConfig,
    AlwaysCondition,
    BinaryScoring,
    BucketConfig,
    BucketedScoring,
    CategoryAllocation,
    CategoryScoreCondition,
    ComparisonOperator,
    ComponentConfig,
    ComponentProfileConfig,
    Direction,
    FuzzyScoringPolicy,
    GradeCutoff,
    GradeInCondition,
    GreenMachineConfig,
    MissingDataPolicy,
    MissingDataRule,
    PredicateComparison,
    QualificationPredicate,
    ScoringMethod,
    SignalClause,
    SignalCondition,
    SignalRule,
    StrongCategoryCountCondition,
    TotalScoreCondition,
)
from .validation_rules import TOTAL_MAX_POINTS, validate_semantics
from .versioning import (
    ConfigurationUseSeal,
    ConfigurationVersionRegistry,
    VersionedConfiguration,
    load_versioned_config,
    load_versioned_config_text,
)

__all__ = [
    "TOTAL_MAX_POINTS",
    "AllocationConfig",
    "AlwaysCondition",
    "BinaryScoring",
    "BucketConfig",
    "BucketedScoring",
    "CategoryAllocation",
    "CategoryScoreCondition",
    "ComparisonOperator",
    "ComponentConfig",
    "ComponentProfileConfig",
    "ConfigHash",
    "ConfigIntegrityError",
    "ConfigParseError",
    "ConfigSchemaError",
    "ConfigSemanticError",
    "ConfigVersionError",
    "ConfigurationUseSeal",
    "ConfigurationVersionRegistry",
    "ConflictingConfigVersionError",
    "Direction",
    "DuplicateConfigVersionError",
    "FuzzyScoringPolicy",
    "GradeCutoff",
    "GradeInCondition",
    "GreenMachineConfig",
    "MalformedConfigHashError",
    "MissingDataPolicy",
    "MissingDataRule",
    "ModifiedAfterUseError",
    "PredicateComparison",
    "QualificationPredicate",
    "ScoringMethod",
    "SignalClause",
    "SignalCondition",
    "SignalRule",
    "SourceModifiedError",
    "SourceUnavailableError",
    "StrictConfigLoader",
    "StrongCategoryCountCondition",
    "TotalScoreCondition",
    "UnknownConfigVersionError",
    "VersionLabelReplacedError",
    "VersionedConfiguration",
    "config_hash",
    "load_config",
    "load_config_text",
    "load_versioned_config",
    "load_versioned_config_text",
    "semantic_projection",
    "source_digest",
    "validate_semantics",
]
