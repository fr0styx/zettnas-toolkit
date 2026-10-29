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

worker_id = os.environ.get("PYTEST_XDIST_WORKER", "")
prefix = f"zettnas-tests-{worker_id}-" if worker_id else "zettnas-tests-"
SANDBOX = tempfile.mkdtemp(prefix=prefix)
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
        # remotes mount here, not under the real /mnt/remotes (found by the random-order nightly)
        "REMOTES_PATH": os.path.join(SANDBOX, "remotes"),
        "HOST_SYS": FAKE_SYS,
        "HOST_PROC": FAKE_PROC,
        "HOST_DEV": FAKE_DEV,
        "ENABLE_FB": "0",
        "LED_PORT": os.path.join(FAKE_DEV, "ttyACM-missing"),
        "NAS_NAME": "TESTNAS",
        "WEB_PASSWORD": "admin",
        "TESTING": "1",
        "ZETTNAS_TEST_MODE": "1",
        "ZETTNAS_FAST_HASH": "1",
        # Most tests log in as admin/admin, so the must-change-password gate is
        # off here; tests/test_sec23_password_change.py turns it back on.
        "ZETTNAS_ENFORCE_PASSWORD_CHANGE": "0",
        # Never reach a real Ollama during tests: port 9 refuses at once, so
        # embedding calls fail fast and take their fallback path.
        "OLLAMA_HOST": "http://127.0.0.1:9",
    }
)

try:
    import backend.config

    backend.config.DATA_DIR = DATA_DIR
    backend.config.CLIENT_PREFS_FILE = os.path.join(DATA_DIR, "client_preferences.json")
    backend.config.DB_PATH = os.path.join(DATA_DIR, "history.db")
    backend.config.FAN_STATE_FILE = os.path.join(DATA_DIR, "fan_state.json")
    backend.config.LED_STATE_FILE = os.path.join(DATA_DIR, "led_state.json")
    backend.config.SCREEN_STATE_FILE = os.path.join(DATA_DIR, "screen_state.json")
    backend.config.EVENTS_FILE = os.path.join(DATA_DIR, "events.json")
    backend.config.BUTTON_CFG_FILE = os.path.join(DATA_DIR, "button_state.json")
    backend.config.SECURITY_FILE = os.path.join(DATA_DIR, "security.json")
    backend.config.SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
    backend.config.USERS_DB_PATH = os.path.join(DATA_DIR, "users.db")
    backend.config.WALLPAPER_CONFIG_FILE = os.path.join(DATA_DIR, "wallpaper_config.json")
    backend.config.WALLPAPERS_DIR = os.path.join(DATA_DIR, "wallpapers")

    from backend.users_db import init_users_db

    init_users_db(backend.config.USERS_DB_PATH)
except Exception:
    pass


# --- ARC-13: each test starts from the same data folder --------------------------------------
# Several tests patch os.stat, os.listdir or os.path.realpath to prove that code never touches
# a disk, and their patches may still be in place when this clean-up runs. It therefore calls
# the posix module directly, which those patches do not reach.
import posix  # noqa: E402
import stat as _stat  # noqa: E402

_DB_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite-wal", ".sqlite-shm")
_RESTORE_MAX_BYTES = 256 * 1024


def _lstat(path):
    try:
        return posix.lstat(path)
    except OSError:
        return None


def _read(path):
    fd = posix.open(path, posix.O_RDONLY)
    try:
        chunks = []
        while chunk := posix.read(fd, 65536):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        posix.close(fd)


def _write(path, data):
    fd = posix.open(path, posix.O_WRONLY | posix.O_CREAT | posix.O_TRUNC, 0o600)
    try:
        posix.write(fd, data)
    finally:
        posix.close(fd)


def _remove(path):
    st = _lstat(path)
    if st is None:
        return
    if _stat.S_ISDIR(st.st_mode):
        for name in posix.listdir(path):
            _remove(path + "/" + name)
        posix.rmdir(path)
    else:
        posix.unlink(path)


def _data_snapshot():
    files = {}
    try:
        names = posix.listdir(DATA_DIR)
    except OSError:
        return files
    for name in names:
        path = DATA_DIR + "/" + name
        st = _lstat(path)
        if name.endswith(_DB_SUFFIXES) or st is None or not _stat.S_ISREG(st.st_mode):
            files[name] = None  # databases keep open connections; folders are left as they are
        elif st.st_size <= _RESTORE_MAX_BYTES:
            try:
                files[name] = _read(path)
            except OSError:
                files[name] = None
        else:
            files[name] = None
    return files


@pytest.fixture(autouse=True)
def _fresh_data_folder():
    """Files a test adds to the data folder are removed after it, and small settings files it
    changed or removed are put back, so no test depends on what an earlier one left behind
    (ARC-13). Databases are left alone (their connections stay open across tests)."""
    before = _data_snapshot()
    yield
    try:
        names = posix.listdir(DATA_DIR)
    except OSError:
        names = []
    for name in names:
        if name.endswith(_DB_SUFFIXES):
            continue
        path = DATA_DIR + "/" + name
        try:
            if name not in before:
                _remove(path)
            elif before[name] is not None and _read(path) != before[name]:
                _write(path, before[name])
        except OSError:
            pass
    for name, old in before.items():
        if old is not None and name not in names:
            try:
                _write(DATA_DIR + "/" + name, old)
            except OSError:
                pass
    try:
        from backend import fsutil

        fsutil.clear_json_cache()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _fresh_health_check():
    """/api/health caches its database check (PERF-30): each test starts without a cached answer."""
    from backend.api import system

    system._DB_CHECK.update(state="", at=0.0)
    yield


@pytest.fixture(autouse=True)
def _web_off():
    """A chat turn sets "web allowed" for its context; each test starts with it off (ARC-13)."""
    from backend.services.chat_web_tools import _WEB_ALLOWED

    token = _WEB_ALLOWED.set(False)
    yield
    _WEB_ALLOWED.reset(token)


@pytest.fixture(autouse=True)
def _fresh_hardware_state():
    """Fan hold trackers, thermal fail-safe flags, standby caches, the detected chassis model and
    drive verdicts start empty (ARC-13; the last two found by the random-order nightly)."""
    from backend.services import rag_standby
    from backend.state import Z_STATE

    Z_STATE.fan_state_tracker.clear()
    Z_STATE.critical_temp_active = False
    Z_STATE.thermal_watchdog_engaged = False
    Z_STATE.cached_smart_data.clear()
    Z_STATE.cached_chassis_model = None
    Z_STATE.drive_verdicts.clear()
    rag_standby._SMARTCTL_STANDBY_CACHE.clear()
    rag_standby._UNRAID_INI_CACHE.update({"ts": 0.0, "disks": {}, "shares": {}})


@pytest.fixture(autouse=True)
def _no_host_storage_tools(request, monkeypatch):
    """Tests see the same storage tools everywhere: none. The Docker test image has no btrfs, ZFS
    or mdadm while GitHub's runner has some, and results must not depend on the machine.
    Tests marked @pytest.mark.real_storage_tools ask shutil.which themselves."""
    from backend.hardware.pal import base

    monkeypatch.setattr(base, "_ZFS_PROBLEM", {})  # the once-per-start ZFS check starts fresh
    if request.node.get_closest_marker("real_storage_tools"):
        return
    monkeypatch.setattr(base, "storage_tools", lambda: {"btrfs": False, "zfs": False, "zpool": False, "mdadm": False})


@pytest.fixture(autouse=True)
def _auto_confirm_destructive_actions(request, monkeypatch):
    """Most API tests call destructive routes directly; treat them as confirmed.

    Tests marked @pytest.mark.real_confirmations exercise the real 428 / token flow.
    """
    if request.node.get_closest_marker("real_confirmations"):
        return
    from backend import confirmations

    monkeypatch.setattr(confirmations, "consume", lambda *a, **k: True)


@pytest.fixture(autouse=True)
def _no_registry_lookups(monkeypatch):
    """Tests never ask the real registry; tests that need a digest set their own."""
    from backend.api import system

    async def _unknown(tag):
        return None

    monkeypatch.setattr(system, "_registry_digest", _unknown)


@pytest.fixture(autouse=True)
def _fresh_smart_velocity_cache():
    from backend import db

    db._VELOCITY_CACHE.clear()
    db._SMART_STORED.clear()
    db._SMART_PRUNED.clear()
    db._METRICS_COLS.clear()


@pytest.fixture(autouse=True)
def _signed_updates(request, monkeypatch):
    """Update tests see a valid CI signature; tests marked real_signatures check the real code."""
    if request.node.get_closest_marker("real_signatures"):
        return
    from backend.services import image_signature

    monkeypatch.setattr(
        image_signature,
        "verify_image",
        lambda digest: image_signature.SignatureResult(True, "test", "https://github.com/test"),
    )


@pytest.fixture(autouse=True)
def _collector_alive(monkeypatch):
    """Tests don't run the stats collector, so /api/health would report it stalled once the
    suite has run longer than the start-up grace (CI is slower than a dev box). Every test
    starts with a fresh heartbeat; health tests set their own."""
    import time

    from backend.state import Z_STATE

    monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time())


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    from backend import rate_limit

    rate_limit.reset()


try:
    from backend.services import rag_reindex_status as _rrs

    _REINDEX_STATUS_AT_START = dict(_rrs.REINDEX_STATUS)
except Exception:
    _REINDEX_STATUS_AT_START = {}


@pytest.fixture(autouse=True)
def _fresh_idle_caches():
    """The idle-loop caches (PERF-5) start empty, so a test sees the files it writes."""
    import backend.config as cfg
    from backend import fsutil
    from backend.hardware import fans, screen
    from backend.hardware.hal import DiskDiscoveryHAL
    from backend.services import rag_reindex_status

    fsutil.clear_json_cache()
    screen._cached_screen_state = None
    screen._screen_checked_at = float("-inf")
    cfg._default_pw_cache["file_at"] = float("-inf")
    fans._APPLIANCE_CACHE.clear()
    DiskDiscoveryHAL.clear_cache()
    rag_reindex_status._REINDEX_CACHE = {"status": "idle"}
    rag_reindex_status._REINDEX_CACHE_TIME = 0.0
    rag_reindex_status._REINDEX_KEY = ""
    rag_reindex_status.REINDEX_STATUS.clear()
    rag_reindex_status.REINDEX_STATUS.update(_REINDEX_STATUS_AT_START)


def _install_response_hook():
    """Every JSON response of the test client goes through one hook (ARCH-11):
    ZETTNAS_RECORD_RESPONSES=<file> records them for scripts/gen_response_models.py;
    otherwise each one is checked against the response schema documented for its route."""
    import json as _json

    from starlette.testclient import TestClient

    if getattr(TestClient, "_zn_response_hook", False):
        return
    record_to = os.environ.get("ZETTNAS_RECORD_RESPONSES")
    original = TestClient.request

    def request(self, method, url, *args, **kwargs):
        resp = original(self, method, url, *args, **kwargs)
        if not (200 <= resp.status_code < 300) or "json" not in resp.headers.get("content-type", ""):
            return resp
        if len(resp.content) > 300_000:
            return resp
        try:
            body = _json.loads(resp.content)
        except ValueError:
            return resp
        path = resp.request.url.path
        if record_to:
            with open(record_to, "a", encoding="utf-8") as f:
                f.write(_json.dumps({"method": method.upper(), "path": path, "body": body}) + "\n")
        else:
            from tests.response_contract import check_response

            check_response(self.app, method.upper(), path, body)
        return resp

    TestClient.request = request
    TestClient._zn_response_hook = True


_install_response_hook()


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


_CACHED_ADMIN_HASH = None


def get_cached_admin_hash() -> str:
    global _CACHED_ADMIN_HASH
    if _CACHED_ADMIN_HASH is None:
        from backend.passwords import hash_password

        _CACHED_ADMIN_HASH = hash_password("admin")
    return _CACHED_ADMIN_HASH


def _reset_admin_password() -> None:
    """Sign-in checks the admin account's own hash, so tests that change it are undone here."""
    from backend.users_db import users_db_session

    with users_db_session(None) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (get_cached_admin_hash(), "admin-00000000-0000-0000-0000-000000000001"),
        )


@pytest.fixture
def webdav_on(monkeypatch):
    """The WebDAV portal only answers while WebDAV is switched on (it is off by default)."""
    from backend.services.webdav_engine import WebdavEngine

    real = WebdavEngine.load_config
    monkeypatch.setattr(WebdavEngine, "load_config", lambda self: {**real(self), "enabled": True})


@pytest.fixture
def client():
    """FastAPI TestClient (lifespan not started: no hardware threads)."""
    from fastapi.testclient import TestClient

    import app as app_module
    from backend import config
    from backend.api import auth as auth_api

    saved_hash = config.STORED_PASSWORD_HASH
    config.STORED_PASSWORD_HASH = get_cached_admin_hash()
    _reset_admin_password()
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


def pytest_addoption(parser):
    parser.addoption(
        "--random-order",
        nargs="?",
        const="random",
        default=os.environ.get("ZETTNAS_RANDOM_ORDER"),
        help="run the tests in a shuffled order (optionally with a seed) to find order dependencies",
    )


def pytest_configure(config):
    seed = config.getoption("--random-order")
    if seed == "random":
        import random

        seed = str(random.SystemRandom().randrange(1, 10**6))
    config._zn_random_seed = seed


def pytest_collection_modifyitems(config, items):
    seed = getattr(config, "_zn_random_seed", None)
    if seed:
        import random

        random.Random(seed).shuffle(items)


def pytest_report_header(config):
    seed = getattr(config, "_zn_random_seed", None)
    return f"random order: seed {seed} (re-run with --random-order={seed})" if seed else None


@pytest.fixture(autouse=True)
def _reset_embed_breaker():
    """A test whose embedder fails trips the shared breaker (AI-27); the next test starts clean."""
    from backend.services import rag_embeddings

    rag_embeddings._EMBED_BREAKER["until"] = 0.0
    yield
    rag_embeddings._EMBED_BREAKER["until"] = 0.0


@pytest.fixture
def search_as_system(monkeypatch):
    """For tests of ranking and indexing, not of permissions: a search without a principal sees
    every file, as it did before SEC-37 (in the app it now sees nothing). Permission tests pass
    real principals."""
    from backend.services import rag_engine_search as res

    real = res.RagSearchMixin._build_rbac_clause

    def as_system(principal, table_alias="f"):
        return real(res.SYSTEM_PRINCIPAL if principal is None else principal, table_alias)

    monkeypatch.setattr(res.RagSearchMixin, "_build_rbac_clause", staticmethod(as_system))
