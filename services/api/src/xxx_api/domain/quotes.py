"""Quote-request and private model-upload state contracts."""

from enum import StrEnum


class QuoteRequestStatus(StrEnum):
    """Server-controlled quote-request workflow states."""

    DRAFT = "draft"
    ANALYZING = "analyzing"
    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_READY = "analysis_ready"
    ESTIMATE_READY = "estimate_ready"
    OWNER_REVIEW = "owner_review"
    QUOTED = "quoted"
    REJECTED = "rejected"


class ModelAssetStatus(StrEnum):
    """Trust state for one uploaded source model."""

    PENDING_UPLOAD = "pending_upload"
    QUARANTINED = "quarantined"
    VALIDATING = "validating"
    VALIDATED = "validated"
    REJECTED = "rejected"


class ModelFormat(StrEnum):
    """MVP source formats; values are stable public API strings."""

    STL = "stl"
    THREE_MF = "3mf"
    OBJ = "obj"
    STEP = "step"


class AnalysisRunStatus(StrEnum):
    """Durable orchestration states for one immutable quote version."""

    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_PROFILE = "awaiting_profile"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AnalysisAssetStatus(StrEnum):
    """Bounded result state for one model in one analysis run."""

    VALIDATED = "validated"
    AWAITING_PROFILE = "awaiting_profile"
    SLICED = "sliced"
    REJECTED = "rejected"
