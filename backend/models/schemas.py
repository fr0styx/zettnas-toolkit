from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    password: str

class SecurityUpdateRequest(BaseModel):
    current_password: str
    new_password: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None

class FanConfigRequest(BaseModel):
    profile: Optional[str] = None
    manual_pct: Optional[int] = None
    ctrl_cpu_fan: Optional[bool] = None
    temp_min: Optional[int] = None
    temp_max: Optional[int] = None
    curve_points: Optional[List[List[int]]] = Field(default=None, max_length=12)

class LedConfigRequest(BaseModel):
    power: Optional[str] = None
    brightness: Optional[int] = None
    color: Optional[str] = None
    color2: Optional[str] = None
    mode: Optional[str] = None
    speed: Optional[int] = None
    reactive: Optional[bool] = None
    night_mode: Optional[bool] = None
    night_start: Optional[str] = None
    night_end: Optional[str] = None

class ButtonConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    source: Optional[str] = None
    dest: Optional[str] = None
    use_exif: Optional[bool] = None
    on_collision: Optional[str] = None

class CopyConfirmRequest(BaseModel):
    action: str = Field(..., description="'skip', 'overwrite', or 'cancel'")

class WallpaperSelectRequest(BaseModel):
    name: str

class WallpaperRenameRequest(BaseModel):
    old_name: str
    new_name: str

class MkdirRequest(BaseModel):
    path: str = Field(..., max_length=4096)


class LayoutRequest(BaseModel):
    order: List[str] = Field(default_factory=list, max_length=32)
    vis: Dict[str, bool] = Field(default_factory=dict)
    sizes: Dict[str, str] = Field(default_factory=dict)
    clock_format: str = Field(default="24", pattern=r"^(12|24)$")
    timezone: str = Field(default="America/New_York", max_length=64, pattern=r"^[A-Za-z0-9_+\-/]+$")


class StateRequest(BaseModel):
    fb: Optional[bool] = None
