"""UX-38 in a real browser: the riskiest paths by keyboard alone, and German with no English left.

Needs the live test server, like test_e2e_a11y.py. Journeys: add a person, sign in with a
recovery code, find a folder in Files and come back, and delete a file and bring it back from the
Recycle Bin with Ctrl+Z.
The German run opens the sign-in screen, the people page and the backup pane at 820 and 390 px
and fails on any visible text that is still the English of a translated key.
"""

import json
import os
import re
import time

import pytest

from tests.test_e2e_a11y import BASE
from tests.test_e2e_integration import is_server_reachable
from tests.test_e2e_keyboard_german import PASSWORD, _browser, _sign_in_with_keyboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.environ.get("ZETTNAS_E2E_MEDIA_DIR") or os.environ.get("POOL_PATH", "")

pytestmark = pytest.mark.skipif(
    not is_server_reachable(BASE) and os.environ.get("ZETTNAS_E2E_REQUIRED") != "1",
    reason="Live ZettNAS Toolkit test server not reachable",
)

FOCUS_ID = "() => document.activeElement && document.activeElement.id"


@pytest.fixture(scope="module", autouse=True)
def admin_can_write():
    """A fresh test server asks the admin for a new password before any change (SEC-13); the
    journeys make changes, so the admin sets the same password once."""
    import urllib.request

    def call(path, body, token=None):
        headers = {"Content-Type": "application/json", "Origin": BASE}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read() or b"{}")

    try:
        login = call("/api/auth/login", {"username": "admin", "password": PASSWORD})
    except Exception as e:
        pytest.fail(f"the admin can't sign in: {e}")
    if login.get("must_change_password"):
        uid = login["user"]["id"]
        call(f"/api/users/{uid}/password", {"new_password": PASSWORD, "current_password": PASSWORD}, login.get("token"))


def _tab_to(page, element_id, limit=40, back=False):
    """Tab (or Shift+Tab) until the element has focus, as a keyboard user would."""
    for _ in range(limit):
        if page.evaluate(FOCUS_ID) == element_id:
            return
        page.keyboard.press("Shift+Tab" if back else "Tab")
    assert page.evaluate(FOCUS_ID) == element_id, f"#{element_id} can't be reached with Tab"


ORIGIN = {"Origin": BASE}  # a cookie session's writes must come from the server's own pages (SEC-17)


def _post(page, path, data=None):
    return page.request.post(BASE + path, data=data or {}, headers=ORIGIN)


def _confirmed(page, action, target):
    r = _post(page, "/api/confirmations", {"action": action, "target": target})
    return {"X-Confirm-Token": r.json()["token"], **ORIGIN}


def _delete_user(page, username):
    users = page.request.get(BASE + "/api/users").json().get("users", [])
    for u in users:
        if u.get("username") == username:
            uid = str(u["id"])
            page.request.delete(BASE + f"/api/users/{uid}", headers=_confirmed(page, "users.delete", uid))


def _sign_in(page):
    """Keyboard sign-in that works at any width (the phone layout has no desktop icons)."""
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
    page.wait_for_timeout(600)
    if page.is_visible("#login-toggle-manual"):
        page.focus("#login-toggle-manual")
        page.keyboard.press("Enter")
    if page.is_visible("#login-username"):
        page.focus("#login-username")
        page.keyboard.press("Control+A")
        page.keyboard.type("admin")
    page.focus("#login-password")
    page.keyboard.press("Control+A")
    page.keyboard.type(PASSWORD)
    page.keyboard.press("Enter")
    page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=10000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)


def _close_wizard(page):
    page.evaluate(
        "() => { const m = document.getElementById('setup-wizard-modal'); if (m) m.classList.remove('open'); }"
    )


def test_add_a_person_by_keyboard():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        _close_wizard(page)
        _delete_user(page, "kbjourney")
        page.evaluate("() => window.openManagementWindow('mgmt-pane-users')")
        page.wait_for_selector("#btn-add-user", state="visible", timeout=8000)
        page.focus("#btn-add-user")
        page.keyboard.press("Enter")
        page.wait_for_selector("#modal-add-user", state="visible", timeout=5000)
        _tab_to(page, "add-user-username")
        page.keyboard.type("kbjourney")
        _tab_to(page, "add-user-display")
        page.keyboard.type("Keyboard Journey")
        _tab_to(page, "add-user-password")
        page.keyboard.type("journey-Pass-1")
        _tab_to(page, "add-user-role")
        page.keyboard.press("ArrowDown")  # family member -> app manager
        for _ in range(20):  # on to the Add button (Enter on a list doesn't submit a form)
            if page.evaluate(
                "() => document.activeElement && document.activeElement.matches('#form-add-user button[type=submit]')"
            ):
                break
            page.keyboard.press("Tab")
        else:
            raise AssertionError("the Add button can't be reached with Tab")
        page.keyboard.press("Enter")
        try:
            page.wait_for_selector("#users-table-body >> text=@kbjourney", timeout=8000)
        finally:
            _delete_user(page, "kbjourney")
        browser.close()


def test_sign_in_with_a_recovery_code_by_keyboard():
    from playwright.sync_api import sync_playwright

    from backend.totp import generate_totp_code

    with sync_playwright() as p:
        browser = _browser(p)
        admin = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(admin)
        _delete_user(admin, "kbrecovery")
        r = _post(
            admin, "/api/users", {"username": "kbrecovery", "password": "recovery-Pass-1", "role_id": "share_user"}
        )
        assert r.ok, r.text()
        try:
            # the person turns two-step sign-in on (through the API: the setup dialog has its own tests)
            own = browser.new_context().new_page()
            assert _post(own, "/api/auth/login", {"username": "kbrecovery", "password": "recovery-Pass-1"}).ok
            setup = _post(own, "/api/auth/mfa/setup").json()
            enabled = _post(
                own,
                "/api/auth/mfa/enable",
                {
                    "secret": setup["secret"],
                    "code": generate_totp_code(setup["secret"]),
                    "current_password": "recovery-Pass-1",
                    "recovery_codes": setup["recovery_codes"],
                },
            )
            assert enabled.ok, enabled.text()
            code = enabled.json()["recovery_codes"][0]

            # ...and later signs in with a recovery code, by keyboard alone
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
            page.wait_for_timeout(600)
            if page.is_visible("#login-toggle-manual"):
                page.focus("#login-toggle-manual")
                page.keyboard.press("Enter")
            page.focus("#login-username")
            page.keyboard.press("Control+A")
            page.keyboard.type("kbrecovery")
            page.focus("#login-password")
            page.keyboard.type("recovery-Pass-1")
            page.keyboard.press("Enter")
            page.wait_for_selector("#login-step-mfa", state="visible", timeout=8000)
            _tab_to(page, "mfa-toggle-recovery")
            page.keyboard.press("Enter")
            assert page.evaluate(FOCUS_ID) == "mfa-challenge-code", "the code field did not take focus"
            page.keyboard.type(code)
            page.keyboard.press("Enter")
            try:
                page.wait_for_function("() => localStorage.getItem('zettnas_signed_in') === '1'", timeout=8000)
            except Exception:
                shown = page.evaluate(
                    "() => [...document.querySelectorAll('#login-error, #login-sso-error, .toast, [role=alert]')].map((e) => e.textContent.trim()).filter(Boolean)"
                )
                raise AssertionError(f"the recovery code did not sign in; the page says: {shown}") from None
        finally:
            _delete_user(admin, "kbrecovery")
        browser.close()


@pytest.fixture
def journey_folder():
    if not POOL or not os.path.isdir(POOL):
        pytest.skip("no browsable pool folder (ZETTNAS_E2E_MEDIA_DIR)")
    folder = os.path.join(POOL, "Keyboard Journey")
    os.makedirs(os.path.join(folder, "Inside"), exist_ok=True)
    with open(os.path.join(folder, "Inside", "note.txt"), "w") as f:
        f.write("found by keyboard\n")
    with open(os.path.join(folder, "restore-me.txt"), "w") as f:
        f.write("bring me back\n")
    yield folder
    import shutil

    shutil.rmtree(folder, ignore_errors=True)


def _open_files_at(page, path, expect):
    page.evaluate(f"() => window.openFileManager && window.openFileManager({json.dumps(path)})")
    page.wait_for_selector(
        f".fm-row[data-path$={json.dumps('/' + expect)}], .fm-grid-card[data-path$={json.dumps('/' + expect)}]",
        timeout=10000,
    )
    page.wait_for_timeout(500)


def _focus_list(page):
    page.evaluate(
        "() => { const w = [...document.querySelectorAll('.file-manager-window')].pop(); (w.querySelector('.fm-file-list, .fm-list, [role=grid], [role=listbox]') || w).focus(); }"
    )


def _select(page, name, limit=30):
    for _ in range(limit):
        sel = page.evaluate(
            "() => [...document.querySelectorAll('.fm-row.selected, .fm-grid-card.selected')].map((e) => e.dataset.path || e.textContent).join('|')"
        )
        if name in sel:
            return
        page.keyboard.press("ArrowDown")
    rows = page.evaluate(
        "() => [...document.querySelectorAll('.fm-row, .fm-grid-card')].map((r) => (r.dataset.path || '') + (r.classList.contains('selected') ? '*' : ''))"
    )
    raise AssertionError(
        f"{name} can't be selected with the arrow keys; rows: {rows}; focus: {page.evaluate(FOCUS_ID)}"
    )


def test_files_by_keyboard(journey_folder):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        _close_wizard(page)
        _open_files_at(page, journey_folder, "Inside")
        _focus_list(page)
        _select(page, "Inside")
        page.keyboard.press("Enter")
        page.wait_for_selector(".file-manager-window >> text=note.txt", timeout=6000)
        page.keyboard.press("Alt+ArrowLeft")
        page.wait_for_selector(".file-manager-window >> text=restore-me.txt", timeout=6000)
        browser.close()


def test_delete_and_restore_by_keyboard(journey_folder):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        _close_wizard(page)
        _open_files_at(page, journey_folder, "restore-me.txt")
        _focus_list(page)
        _select(page, "restore-me.txt")
        page.keyboard.press("Delete")
        page.wait_for_timeout(500)
        page.keyboard.press("Enter")  # the confirm dialog's default button
        deadline = time.time() + 8
        while os.path.exists(os.path.join(journey_folder, "restore-me.txt")) and time.time() < deadline:
            time.sleep(0.3)
        assert not os.path.exists(os.path.join(journey_folder, "restore-me.txt")), (
            "Delete did not move the file to the Recycle Bin"
        )
        # the "Moved to the Recycle Bin" message offers Undo; Ctrl+Z takes it (UX-27) and brings the file back
        page.wait_for_selector("button:has-text('Undo')", state="visible", timeout=8000)
        page.keyboard.press("Control+z")
        deadline = time.time() + 8
        while not os.path.exists(os.path.join(journey_folder, "restore-me.txt")) and time.time() < deadline:
            time.sleep(0.3)
        assert os.path.exists(os.path.join(journey_folder, "restore-me.txt")), "Restore did not bring the file back"
        browser.close()


def _strings(lang):
    with open(os.path.join(ROOT, "frontend", "src", "locales", f"{lang}.js"), encoding="utf-8") as f:
        src = f.read()
    return {m.group(1): json.loads(m.group(2)) for m in re.finditer(r'\n  "([^"]+)": ("(?:[^"\\]|\\.)*")', src)}


VISIBLE_TEXT = """(root) => {
  const out = [];
  const walk = document.createTreeWalker(root || document.body, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const el = walk.currentNode.parentElement;
    const text = walk.currentNode.textContent.trim();
    if (!text || !el || !el.getClientRects().length) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none' || el.closest('[hidden], [aria-hidden="true"], script, style, code')) continue;
    out.push(text);
  }
  return out;
}"""

# the screens translated first (UX-21): what a German speaker sees there must be German
GERMAN_SCREENS = [
    ("sign-in", None, "#login-overlay"),
    ("people", "mgmt-pane-users", "#mgmt-pane-users"),
    ("backups", "mgmt-pane-backups", "#mgmt-pane-backups"),
]


@pytest.mark.parametrize("width,height", [(820, 1180), (390, 844)])
def test_german_shows_no_english(width, height):
    from playwright.sync_api import sync_playwright

    en, de = _strings("en"), _strings("de")
    # English of keys whose German differs: seeing one of these on a German screen is a leftover
    english = {v.strip() for k, v in en.items() if "{" not in v and len(v.strip()) > 3 and de.get(k, v) != v}
    found = {}
    with sync_playwright() as p:
        browser = _browser(p)
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_init_script("localStorage.setItem('zettnas_language', 'de')")
        page = context.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
        page.wait_for_timeout(1500)
        for name, pane, root in GERMAN_SCREENS:
            if pane:
                if name == "people" and not page.evaluate("() => localStorage.getItem('zettnas_signed_in') === '1'"):
                    _sign_in(page)
                    _close_wizard(page)
                page.evaluate(f"() => window.openManagementWindow && window.openManagementWindow({json.dumps(pane)})")
                try:
                    page.wait_for_selector(root, state="visible", timeout=8000)
                except Exception:
                    found[name] = ["(the screen did not open)"]
                    continue
                page.wait_for_timeout(1500)
            texts = page.evaluate(VISIBLE_TEXT, page.query_selector(root))
            left = sorted({t for t in texts if t in english})
            if left:
                found[name] = left
        browser.close()
    assert not found, f"English left on German screens at {width} px:\n" + json.dumps(
        found, indent=1, ensure_ascii=False
    )
