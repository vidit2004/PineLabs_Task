from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Window(Contract):
    start: date
    end: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def calendar_date(cls, value):
        if type(value) is date:
            return value
        if isinstance(value, str):
            parsed = date.fromisoformat(value)
            if parsed.isoformat() == value:
                return parsed
        raise ValueError("Use a YYYY-MM-DD calendar date")

    @model_validator(mode="after")
    def check_length(self) -> Self:
        if not 1 <= (self.end - self.start).days <= 31:
            raise ValueError("Each window must span 1 to 31 days")
        return self


class AnalysisPlan(Contract):
    intent: Literal["compare"]
    metric: Literal["success_rate"]
    group_by: Literal["bank"]
    baseline: Window
    current: Window
    bank_ids: tuple[StrictStr, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def check_windows(self) -> Self:
        if (self.baseline.end > self.current.start or
                self.baseline.end - self.baseline.start != self.current.end - self.current.start):
            raise ValueError("Use ordered, non-overlapping windows of equal length")
        return self


class TrendPlan(Contract):
    intent: Literal["trend"]
    metric: Literal["success_rate"]
    group_by: Literal["overall"]
    window: Window
    bank_ids: tuple[StrictStr, ...] | None = Field(default=None, min_length=1)


class Clarification(Contract):
    question: StrictStr = Field(min_length=1)
