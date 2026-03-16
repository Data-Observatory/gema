"""Input schema for dataset metadata enrichment."""

from pydantic import BaseModel, ConfigDict


class DatasetInput(BaseModel):
    """Input data for metadata enrichment.

    Minimum required: url
    Optional: title, description, publisher, frequency, fetched_content
    """

    model_config = ConfigDict(extra="allow")

    url: str
    title: str | None = None
    description: str | None = None
    publisher: str | None = None
    frequency: str | None = None
    fetched_content: str | None = None
