from datetime import datetime

import strawberry

from app.models.project import Project as ProjectModel


@strawberry.type(name="Project")
class ProjectType:
    id: strawberry.ID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, model: ProjectModel) -> "ProjectType":
        return cls(
            id=strawberry.ID(str(model.id)),
            name=model.name,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
