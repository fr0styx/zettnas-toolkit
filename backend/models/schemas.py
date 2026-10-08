from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str


class SecurityUpdateRequest(BaseModel):
    current_password: str
    new_password: str | None = None
    username: str | None = None
    email: str | None = None


class FanConfigRequest(BaseModel):
    profile: str | None = None
    manual_pct: int | None = None
    ctrl_cpu_fan: bool | None = None
    temp_min: int | None = None
    temp_max: int | None = None
    zero_rpm_enabled: bool | None = None
    zero_rpm_nvme_ceiling: int | None = Field(default=None, ge=40, le=70)
    zero_rpm_stop_temp: int | None = Field(default=None, ge=25, le=45)
    zero_rpm_start_temp: int | None = Field(default=None, ge=30, le=55)
    curve_points: list[list[int]] | None = Field(default=None, max_length=12)
    nvme_curve_points: list[list[int]] | None = Field(default=None, max_length=12)
    cpu_curve_points: list[list[int]] | None = Field(default=None, max_length=12)
    zone1_curve_points: list[list[int]] | None = Field(default=None, max_length=12)
    zone2_curve_points: list[list[int]] | None = Field(default=None, max_length=12)


class FanPresetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_\-\s]+$")
    curve_points: list[list[int]] = Field(..., min_length=2, max_length=12)
    nvme_curve_points: list[list[int]] | None = Field(default=None, max_length=12)
    cpu_curve_points: list[list[int]] | None = Field(default=None, max_length=12)


class LedConfigRequest(BaseModel):
    power: str | None = None
    brightness: int | None = None
    color: str | None = None
    color2: str | None = None
    mode: str | None = None
    speed: int | None = None
    reactive: bool | None = None
    night_mode: bool | None = None
    night_start: str | None = None
    night_end: str | None = None


class ScreenConfigRequest(BaseModel):
    brightness: int | None = Field(default=None, ge=0, le=100)
    night_mode: bool | None = None
    night_start: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    night_end: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    night_brightness: int | None = Field(default=None, ge=0, le=100)


class ButtonConfigRequest(BaseModel):
    enabled: bool | None = None
    action: str | None = None
    source: str | None = None
    dest: str | None = None
    use_exif: bool | None = None
    on_collision: str | None = None
    auto_ingest: bool | None = None
    require_confirmation: bool | None = None
    verify_checksum: bool | None = None


class StartCopyRequest(BaseModel):
    source: str | None = None
    dest: str | None = None
    use_exif: bool | None = None


class EjectMediaRequest(BaseModel):
    slot: str = "sd"


class CopyConfirmRequest(BaseModel):
    action: str = Field(..., description="'skip', 'overwrite', or 'cancel'")


class WallpaperSelectRequest(BaseModel):
    # The UI historically sent `filename`; accept either. Empty/None clears.
    name: str | None = Field(default=None, max_length=255)
    filename: str | None = Field(default=None, max_length=255)


class WallpaperRenameRequest(BaseModel):
    old_name: str = Field(..., max_length=255)
    new_name: str = Field(..., max_length=255)


class MkdirRequest(BaseModel):
    path: str = Field(..., max_length=4096)


class LayoutRequest(BaseModel):
    order: list[str] = Field(default_factory=list, max_length=32)
    vis: dict[str, bool] = Field(default_factory=dict)
    sizes: dict[str, str] = Field(default_factory=dict)
    clock_format: str = Field(default="24", pattern=r"^(12|24)$")
    timezone: str = Field(default="America/New_York", max_length=64, pattern=r"^[A-Za-z0-9_+\-/]+$")


class StateRequest(BaseModel):
    fb: bool | None = None


class LcdPageRequest(BaseModel):
    page: int | None = Field(default=None, ge=0, le=3)
    cycle_seconds: int | None = Field(default=None, ge=0, le=300)


class SystemProfileRequest(BaseModel):
    profile: str = Field(..., pattern=r"^(auto|quiet|balanced|performance)$")


class DockerActionRequest(BaseModel):
    action: str = Field(..., pattern=r"^(start|stop|restart|pause|unpause)$")


class DiskSmartTestRequest(BaseModel):
    dev: str = Field(default="sda", max_length=64)
    test_type: str = Field(default="short", pattern=r"^(short|long|conveyance|offline)$")
