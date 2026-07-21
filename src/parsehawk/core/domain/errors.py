class ParseHawkError(Exception):
    """Base exception for expected ParseHawk failures."""


class NotFoundError(ParseHawkError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(f"{resource} not found: {resource_id}")
        self.resource = resource
        self.resource_id = resource_id


class ValidationFailure(ParseHawkError):
    """Raised when a request cannot be accepted."""


class ExtractionCancelled(ParseHawkError):
    """Raised when cooperative cancellation stops an extraction in progress."""


class ProviderRequestError(ParseHawkError):
    """Raised when a model provider rejects a request (e.g. an unknown model).

    Carries the provider's HTTP status when available so the API can surface it
    (a 4xx from the provider becomes a 400 to the caller).
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class PersistenceBusyError(ParseHawkError):
    """Raised when persistence lock contention exceeds the configured wait."""

    code = "persistence_busy"
    retryable = True

    def __init__(self) -> None:
        super().__init__("Persistence is temporarily busy; retry the request")
