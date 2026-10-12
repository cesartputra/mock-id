from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    debtor_type: Literal['individual', 'business', 'deceased']
    preview: bool = False
    session_id: str | None = None
    verification_id: str | None = None
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=120, pattern=r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    phone: str = Field(min_length=9, max_length=18, pattern=r'^\+?[0-9]{9,16}$')
    address: str = Field(min_length=5, max_length=250)
    purpose: Literal['personal', 'application', 'correction']
