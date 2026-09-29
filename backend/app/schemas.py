from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    id: str
    name: str
    email: str


class SettingsIn(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ProjectIn(BaseModel):
    prompt: str = Field(min_length=4, max_length=4000)


class ReviseIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


class PreviewStateIn(BaseModel):
    snapshot: dict[str, str]


class RuntimeCheck(BaseModel):
    key: str
    index: int
    ok: bool
    detail: str = ""


class AcceptanceIn(BaseModel):
    runtime: list[RuntimeCheck] = []
