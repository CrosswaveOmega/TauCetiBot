from typing import *

# pylint: disable=no-name-in-module
from pydantic import BaseModel
from datetime import datetime, timezone


class BaseApiModel(BaseModel):
    """Base extended model class"""

    retrieved_at: Optional[datetime] = None

    def __init__(self, **data):
        super().__init__(**data)
        if "retrieved_at" not in data:
            self.retrieved_at = datetime.now(tz=timezone.utc)
        else:
            self.retrieved_at = datetime.fromisoformat(data["retrieved_at"]).replace(
                tzinfo=timezone.utc
            )

    def __getitem__(self, attr):
        """
        Get a field in the same manner as a dictionary.
        """
        return getattr(self, attr)

    def get(self, attr, default=None):
        if not hasattr(self, attr):
            return default
        return getattr(self, attr)


class HealthMixin:
    health: int
    maxHealth: int

    def health_percent(self):
        value = self.health / max(self.maxHealth, 1)
        return round(value * 100.0,3)
