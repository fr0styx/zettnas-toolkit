"""
Shared pytest fixtures.

The backend reads its configuration from environment variables at import
time, so the sandbox (data dir, fake sysfs, browse roots) is created and
exported *before* any `backend` module is imported.
"""

import os
import shutil
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="zettnas-tests-")
DATA_DIR = os.path.join(SANDBOX, "data")
POOL_DIR = os.path.join(SANDBOX, "pool")
OUTSIDE_DIR = os.path.join(SANDBOX, "outside")
FAKE_SYS = os.path.join(SANDBOX, "sys")
FAKE_PROC = os.path.join(SANDBOX, "proc")
FAKE_DEV = os.path.join(SANDBOX, "dev")

for d in (DATA_DIR, POOL_DIR, OUTSIDE_DIR, FAKE_SYS, FAKE_PROC, FAKE_DEV):
    os.makedirs(d, exist_ok=True)

os.environ.update(
    {
        "DATA_DIR": DATA_DIR,
        "POOL_PATH": POOL_DIR,
        "BROWSE_ROOTS": POOL_DIR,
        "HOST_SYS": FAKE_SYS,
        "HOST_PROC": FAKE_PROC,
        "HOST_DEV": FAKE_DEV,
        "ENABLE_FB": "0",
        "LED_PORT": os.path.join(FAKE_DEV, "ttyACM-missing"),
        "NAS_NAME": "TESTNAS",
        "WEB_PASSWORD": "admin",
    }
)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(SANDBOX, ignore_errors=True)


@pytest.fixture
def paths():
    return {"data": DATA_DIR, "pool": POOL_DIR, "outside": OUTSIDE_DIR, "sys": FAKE_SYS}


@pytest.fixture
def pool_tree():
    """A small directory tree inside the allowed root, plus an escaping symlink."""
    for sub in ("media", "media/photos", "backups"):
        os.makedirs(os.path.join(POOL_DIR, sub), exist_ok=True)
    with open(os.path.join(POOL_DIR, "media", "readme.txt"), "w") as f:
        f.write("hello")
    os.makedirs(os.path.join(OUTSIDE_DIR, "secret"), exist_ok=True)
    link = os.path.join(POOL_DIR, "escape")
    if not os.path.lexists(link):
        os.symlink(OUTSIDE_DIR, link)
    yield POOL_DIR


@pytest.fixture
def fake_hwmon():
    """Fake zettlab_d8_fans hwmon: pwm1/2 with read-only *_enable (always
    manual, like the real driver) and pwm3 with a writable enable (CPU fan)."""
    from backend.state import Z_STATE

    hw = os.path.join(FAKE_SYS, "class", "hwmon", "hwmon7")
    if os.path.isdir(hw):
        for name in os.listdir(hw):
            fp = os.path.join(hw, name)
            os.chmod(fp, 0o644)
        shutil.rmtree(hw)
    os.makedirs(hw)

    def put(name, value, mode=0o644):
        fp = os.path.join(hw, name)
        with open(fp, "w") as f:
            f.write(f"{value}\n")
        os.chmod(fp, mode)

    put("name", "zettlab_d8_fans")
    put("pwm1", 90)
    put("pwm2", 35)
    put("pwm3", 0)
    put("pwm1_enable", 1, 0o444)
    put("pwm2_enable", 1, 0o444)
    put("pwm3_enable", 2)
    put("fan1_input", 1300)
    put("fan2_input", 820)
    put("fan3_input", 2800)

    saved = (Z_STATE.cached_hwmon, Z_STATE.fans_locked, Z_STATE.fans_released)
    Z_STATE.cached_hwmon = None
    Z_STATE.fans_locked = False
    Z_STATE.fans_released = False
    yield hw
    Z_STATE.cached_hwmon, Z_STATE.fans_locked, Z_STATE.fans_released = saved
    Z_STATE.cached_hwmon = None


def read_sysfs(hw, name):
    with open(os.path.join(hw, name)) as f:
        return f.read().strip()


@pytest.fixture
def client():
    """FastAPI TestClient (lifespan not started: no hardware threads)."""
    from fastapi.testclient import TestClient

    import app as app_module
    from backend import config
    from backend.api import auth as auth_api
    from backend.passwords import hash_password

    saved_hash = config.STORED_PASSWORD_HASH
    config.STORED_PASSWORD_HASH = hash_password("admin")
    auth_api._failures.clear()
    yield TestClient(app_module.app)
    auth_api._failures.clear()
    config.STORED_PASSWORD_HASH = saved_hash


@pytest.fixture
def token(client):
    r = client.post("/api/auth/login", json={"password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
