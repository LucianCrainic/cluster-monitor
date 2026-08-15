"""Shared model configuration."""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Strict base model used by public API schemas."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
