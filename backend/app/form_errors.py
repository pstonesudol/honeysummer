"""Validation errors that identify an admin form control without changing API text."""


class FieldValidationError(ValueError):
    """A validation error naming the admin form control that failed."""

    def __init__(self, message: str, field: str):
        """Store the message and the form field that caused it."""
        super().__init__(message)
        self.field = field
