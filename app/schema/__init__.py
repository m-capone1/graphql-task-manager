import strawberry

from app.schema.mutations.task import Mutation
from app.schema.queries.task import Query

schema = strawberry.Schema(query=Query, mutation=Mutation)
