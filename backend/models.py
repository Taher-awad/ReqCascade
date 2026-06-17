"""Pydantic models for API request/response validation."""
from pydantic import BaseModel, Field


class PipelineRequest(BaseModel):
    input_text: str = Field(default="", description="Raw natural language or PRD text")
    model: str = Field(default="gemini-2.5-flash", description="Gemini model to use")


class ExpandRequest(BaseModel):
    parent_data: dict = Field(description="The parent node's data payload")
    stage: str = Field(description="The stage to generate (hlfr, llfr, tr, tc)")
    model: str = Field(default="gemini-2.5-flash", description="Gemini model to use")


class HealthResponse(BaseModel):
    status: str
    gemini_connected: bool
    available_models: list[str]
