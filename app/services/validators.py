from pydantic import BaseModel, ValidationError as PydanticValidationError, field_validator

TITLE_MAX = 500
DESCRIPTION_MAX = 10_000


def validate_title(value: str | None) -> str:
    if value is None:
        raise ValueError("Title cannot be empty")
    stripped = value.strip()
    if not stripped:
        raise ValueError("Title cannot be empty")
    if len(stripped) > TITLE_MAX:
        raise ValueError(f"Title must be {TITLE_MAX} characters or fewer")
    return stripped


def validate_description(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) > DESCRIPTION_MAX:
        raise ValueError(f"Description must be {DESCRIPTION_MAX:,} characters or fewer")
    return value.strip() or None


class CreateTaskData(BaseModel):
    title: str
    description: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, v: str) -> str:
        return validate_title(v)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, v: str | None) -> str | None:
        return validate_description(v)


def extract_pydantic_error(exc: PydanticValidationError) -> tuple[str, str | None]:
    """Return (message, field_name) from the first Pydantic validation error."""
    first = exc.errors()[0]
    field = str(first["loc"][0]) if first["loc"] else None
    msg = first["msg"]
    # Pydantic v2 prepends "Value error, " to messages from ValueError in validators.
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return msg, field
