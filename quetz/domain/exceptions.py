"""Domain exceptions for the Quetz-AI agent.

These are the typed, domain-specific failures that the application and
presentation layers can catch and translate into user-facing errors.
All business exceptions inherit from a single base so callers can handle
them uniformly without knowing the concrete type.
"""


class QuetzError(Exception):
    """Base class for all domain/critical business errors."""


class TaskError(QuetzError):
    """Raised when a task is missing or malformed."""


class PlanError(QuetzError):
    """Raised when a plan is empty, too short, or otherwise unusable."""


class AgentTerminated(QuetzError):
    """Raised when execution is intentionally aborted (e.g. by the user)."""


class WorkflowError(QuetzError):
    """Raised for failures during workflow construction or orchestration."""


class ContextError(QuetzError):
    """Raised when the context compiler cannot produce a usable bundle."""


class ProjectIndexError(QuetzError):
    """Raised when the project index cannot be built or queried."""


class EditError(QuetzError):
    """Raised when an edit plan is malformed or cannot be applied safely."""


class ValidationError(QuetzError):
    """Raised when acceptance validation cannot run."""
