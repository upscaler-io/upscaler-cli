"""CLI error types and exit codes.

Exit codes:
    0: Success
    1: Error (API error, invalid input, etc.)
    2: Authentication required (not logged in, session expired)
"""


class CLIError(Exception):
    """Base CLI error with exit code."""

    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class AuthRequiredError(CLIError):
    """Authentication required — user needs to run 'upscaler login'."""

    def __init__(self, message: str = "Not authenticated. Run: upscaler login"):
        super().__init__(message, exit_code=2)


class APIError(CLIError):
    """API returned an error response."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message, exit_code=1)
        self.status_code = status_code
