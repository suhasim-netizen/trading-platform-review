"""Broker-agnostic errors surfaced by adapters (never raw HTTP/SDK types).

Hierarchy: ``BrokerError`` → ``BrokerAuthError`` (and ``BrokerTokenExpiredError``),
``BrokerNetworkError``, ``BrokerRateLimitError``, ``BrokerValidationError``.
"""


class BrokerError(Exception):
    """Base class for adapter failures."""


class BrokerAuthError(BrokerError):
    """Invalid credentials, revoked access, or failed token exchange."""


class BrokerTokenExpiredError(BrokerAuthError):
    """Access token is expired and could not be refreshed."""


class BrokerNetworkError(BrokerError):
    """Transient connectivity or timeout failure."""


class BrokerRateLimitError(BrokerError):
    """Broker rejected the request due to rate limiting."""


class BrokerValidationError(BrokerError):
    """Request or response failed platform validation."""
