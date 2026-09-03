from __future__ import annotations

import requests


RETRYABLE_EXIT_CODE = 75

_RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429})


class RetryableOperationalError(RuntimeError):
    """A proven transient failure at a safely repeatable boundary."""


def is_retryable_provider_error(error: BaseException) -> bool:
    """Return whether a provider exception is proven transient."""

    if isinstance(error, RetryableOperationalError):
        return True

    if isinstance(error, (requests.Timeout, requests.ConnectionError)):
        return True

    if isinstance(error, requests.HTTPError):
        response = error.response
        status_code = (
            None if response is None else response.status_code
        )
        return (
            status_code in _RETRYABLE_HTTP_STATUS_CODES
            or (
                status_code is not None
                and 500 <= status_code <= 599
            )
        )

    return False


def operational_failure_exit_code(error: BaseException) -> int:
    """Map a safely classified CLI failure to its process exit code."""

    return RETRYABLE_EXIT_CODE if is_retryable_provider_error(error) else 1
