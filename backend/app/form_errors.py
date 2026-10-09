"""Validation errors that identify an admin form control without changing API text."""


class FieldValidationError(ValueError):
    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.field = field
