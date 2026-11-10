from typing import Literal
from pydantic import BaseModel, EmailStr, Field


UserRole = Literal['claim_officer', 'insurance_admin', 'system_admin']


class Register(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8)
    # Accepted for backwards compatibility, but public registration ignores it.
    role: UserRole = 'claim_officer'


class UserProvision(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=150)
    password: str = Field(min_length=8)
    role: UserRole


class Login(BaseModel): email: EmailStr; password: str
