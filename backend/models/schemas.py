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
    curve_points: Optional[List[List[int]]] = None

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
    path: str
