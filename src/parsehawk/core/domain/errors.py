class ParseHawkError(Exception):
    """Base exception for expected ParseHawk failures."""


class NotFoundError(ParseHawkError):
    def __init__(self, resource: str, resource_id: str) -> None:
        super().__init__(f"{resource} not found: {resource_id}")
        self.resource = resource
        self.resource_id = resource_id


class ValidationFailure(ParseHawkError):
    """Raised when a request cannot be accepted."""
