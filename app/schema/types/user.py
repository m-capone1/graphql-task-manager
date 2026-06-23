from datetime import datetime

import strawberry

from app.models.user import User as UserModel


@strawberry.type(name="User")
class UserType:
    id: strawberry.ID
    email: str
    name: str
    created_at: datetime

    @classmethod
    def from_orm(cls, model: UserModel) -> "UserType":
        return cls(
            id=strawberry.ID(str(model.id)),
            email=model.email,
            name=model.name,
            created_at=model.created_at,
        )
