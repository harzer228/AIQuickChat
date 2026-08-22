"""Shared exceptions for all API clients."""


class APIError(Exception):
    """Base error for network/API failures.

    Attributes:
        message: human readable message (shown to the user).
        code:    machine readable error code (auth, network, timeout, ...).
        detail:  technical detail (shown in expandable block).
    """

    def __init__(self, message, code="error", detail=""):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail

    def __str__(self):
        return self.message


class GenerationCancelled(Exception):
    """Raised inside a streaming generator when the user stops generation."""
