class ServiceError(Exception):
    """Base class for all service-layer errors."""


class NotFoundError(ServiceError):
    def __init__(self, resource: str, id: str) -> None:
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} '{id}' not found")


class ValidationError(ServiceError):
    def __init__(self, message: str, field: str | None = None) -> None:
        self.message = message
        self.field = field
        super().__init__(message)


class ConflictError(ServiceError):
    def __init__(self, message: str, current_version: int) -> None:
        self.message = message
        self.current_version = current_version
        super().__init__(message)


class ForbiddenError(ServiceError):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)
