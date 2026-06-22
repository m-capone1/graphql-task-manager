import strawberry


@strawberry.type
class NotFoundError:
    message: str


@strawberry.type
class ValidationError:
    message: str
    field: str | None = None


@strawberry.type
class ConflictError:
    message: str
    current_version: int | None = None


@strawberry.type
class ForbiddenError:
    message: str


@strawberry.type
class DeleteSuccess:
    id: strawberry.ID
