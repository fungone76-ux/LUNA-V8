"""Luna RPG - Base Model Classes.

Base Pydantic model with strict validation configuration.
"""
from pydantic import BaseModel, ConfigDict


class LunaBaseModel(BaseModel):
    """Base model for all Luna RPG data structures.
    
    Enforces strict validation, no extra fields, and enum value usage.
    """
    model_config = ConfigDict(
        strict=True,
        validate_assignment=True,
        extra="forbid",
        use_enum_values=True,
    )
