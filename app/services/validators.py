from typing import Optional

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError, field_validator


class CreateTaskData(BaseModel):
    title: str = Field(..., max_length=500)
    description: Optional[str] = Field(None, max_length=10_000)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        return v

    @field_validator("description")
    @classmethod
    def normalize_description(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


def extract_pydantic_error(exc: PydanticValidationError) -> tuple[str, str | None]:
    """Return (message, field_name) from the first Pydantic validation error."""
    first = exc.errors()[0]
    field = str(first["loc"][0]) if first["loc"] else None
    msg = first["msg"]
    # Pydantic v2 prepends "Value error, " to messages from ValueError in validators.
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return msg, field
