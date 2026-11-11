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
POOL = os.environ.get("KIBOTO_E2E_MEDIA_DIR") or os.environ.get("POOL_PATH", "")

pytestmark = pytest.mark.skipif(
    not is_server_reachable(BASE) and os.environ.get("KIBOTO_E2E_REQUIRED") != "1",
    reason="Live Kiboto test server not reachable",
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
    page.wait_for_function("() => localStorage.getItem('kiboto_signed_in') === '1'", timeout=10000)
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
        # the dialog moves focus inside itself a moment after it opens; Tab before that wanders the page
        page.wait_for_function(
            "() => document.getElementById('modal-add-user').contains(document.activeElement)", timeout=5000
        )
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
                page.wait_for_function("() => localStorage.getItem('kiboto_signed_in') === '1'", timeout=8000)
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
        pytest.skip("no browsable pool folder (KIBOTO_E2E_MEDIA_DIR)")
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


def test_rename_sort_and_the_menu_on_empty_space(journey_folder):
    """SET-05: rename works (it answered 422 for every way in), the sort by Modified survives a
    refresh with its arrow, and a right-click on empty space opens a menu while one item is selected."""
    from playwright.sync_api import sync_playwright

    old, new = os.path.join(journey_folder, "restore-me.txt"), os.path.join(journey_folder, "renamed by F2.txt")
    os.utime(old, (1_000_000_000, 1_000_000_000))  # the oldest item: last when the newest comes first
    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        _close_wizard(page)
        _open_files_at(page, journey_folder, "restore-me.txt")
        _focus_list(page)
        _select(page, "restore-me.txt")

        # the menu on empty space, with one item selected
        box = page.locator(".file-manager-window .fm-viewport").last.bounding_box()
        page.mouse.click(box["x"] + box["width"] - 40, box["y"] + box["height"] - 30, button="right")
        page.wait_for_selector("#fm-context-menu [data-act=paste]", state="visible", timeout=4000)
        page.keyboard.press("Escape")

        # rename with F2
        _focus_list(page)
        _select(page, "restore-me.txt")
        page.keyboard.press("F2")
        page.wait_for_selector(".file-manager-window input.fm-inline-rename-input")
        page.keyboard.press("Control+a")
        page.keyboard.type("renamed by F2.txt")
        page.keyboard.press("Enter")
        deadline = time.time() + 8
        while not os.path.exists(new) and time.time() < deadline:
            time.sleep(0.3)
        assert os.path.exists(new) and not os.path.exists(old), "F2 did not rename the file"
        page.wait_for_selector(".file-manager-window >> text=renamed by F2.txt", timeout=6000)

        # sort by Modified, newest first; the folder was written last, the renamed file is the oldest
        # (through the menu on empty space: the first window is too narrow to show that column)
        for act in ("sort-mtime", "sort-desc"):
            page.mouse.click(box["x"] + box["width"] - 40, box["y"] + box["height"] - 30, button="right")
            page.click(f"#fm-context-menu [data-act={act}]")
        names = "() => [...[...document.querySelectorAll('.file-manager-window')].pop().querySelectorAll('.fm-row')].map((r) => r.dataset.path.split('/').pop())"
        assert page.evaluate(names)[-1] == "renamed by F2.txt"
        page.locator(".file-manager-window .fm-refresh-btn").last.click()
        page.wait_for_timeout(1200)
        assert page.evaluate(names)[-1] == "renamed by F2.txt", "the sort was lost at the refresh"
        head = "(c) => { const el = [...document.querySelectorAll('.file-manager-window .fm-header-row .fm-col-' + c)].pop(); return [el.getAttribute('aria-label'), el.textContent.trim()]; }"
        assert page.evaluate(head, "mtime") == ["Modified (Descending)", "Modified ▼"], (
            "the arrow left the column that sorts"
        )
        assert page.evaluate(head, "name") == ["Name", "Name"]
        browser.close()


def test_an_upload_onto_a_taken_name_asks(journey_folder, tmp_path):
    """SET-05, the owner's decision S16: the same name twice asks Replace, Keep both or Skip.
    It used to replace the file with no question and no copy in the Recycle Bin."""
    from playwright.sync_api import sync_playwright

    local = tmp_path / "restore-me.txt"
    local.write_text("the one from my computer\n")
    here = lambda name: os.path.join(journey_folder, name)  # noqa: E731

    def wait_for(path, what):
        deadline = time.time() + 8
        while not os.path.exists(path) and time.time() < deadline:
            time.sleep(0.3)
        assert os.path.exists(path), what

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in_with_keyboard(page)
        _close_wizard(page)
        _open_files_at(page, journey_folder, "restore-me.txt")
        picker = page.locator(".file-manager-window .fm-file-upload-input").last
        assert page.locator(".file-manager-window .fm-upload-btn").last.get_attribute("aria-label") == "Upload files"

        picker.set_input_files(str(local))
        page.wait_for_selector(".fm-upload-taken", timeout=6000)
        assert "restore-me.txt" in page.inner_text(".fm-upload-taken")
        page.click(".fm-upload-taken [data-choice=keep_both]")
        wait_for(here("restore-me (2).txt"), "Keep both did not save the second file")
        with open(here("restore-me.txt")) as f:
            assert f.read() == "bring me back\n", "the file that was there was changed"

        picker.set_input_files(str(local))
        page.wait_for_selector(".fm-upload-taken", timeout=6000)
        page.click(".fm-upload-taken [data-choice=skip]")
        page.wait_for_selector(".fm-upload-taken", state="detached", timeout=4000)
        page.wait_for_timeout(800)
        assert sorted(n for n in os.listdir(journey_folder) if n.startswith("restore-me")) == [
            "restore-me (2).txt",
            "restore-me.txt",
        ]

        picker.set_input_files(str(local))
        page.wait_for_selector(".fm-upload-taken", timeout=6000)
        page.click(".fm-upload-taken [data-choice=replace]")
        deadline = time.time() + 8
        while time.time() < deadline:
            with open(here("restore-me.txt")) as f:
                if f.read() == "the one from my computer\n":
                    break
            time.sleep(0.3)
        with open(here("restore-me.txt")) as f:
            assert f.read() == "the one from my computer\n", "Replace did not put the new file in place"
        binned = page.evaluate("() => fetch('/api/fs/trash', {credentials: 'include'}).then((r) => r.json())")
        assert any(str(i.get("original_path", "")).endswith("/restore-me.txt") for i in binned["items"]), (
            "the replaced file is not in the Recycle Bin"
        )
        browser.close()


@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_a_deleted_file_comes_back_from_the_bin_with_one_tap(journey_folder, width, height):
    """SET-05: the Recycle Bin has a Restore button on each row, on a computer and on a phone, and
    says how long items stay. Restore was reachable only by right-click."""
    from playwright.sync_api import sync_playwright

    gone = os.path.join(journey_folder, "restore-me.txt")
    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": width, "height": height}).new_page()
        _sign_in(page)
        _close_wizard(page)
        deleted = _post(page, "/api/fs/delete", {"path": gone})
        assert deleted.status == 200 and not os.path.exists(gone), deleted.text()
        bins = page.evaluate("() => fetch('/api/fs/trash', {credentials: 'include'}).then((r) => r.json())")
        mine = next(i for i in bins["items"] if str(i.get("original_path", "")).endswith("/restore-me.txt"))
        bin_folder = mine["path"][: mine["path"].index("/.RecycleBin") + len("/.RecycleBin")]
        _open_files_at(page, bin_folder, os.path.basename(mine["path"]))

        window = page.locator(".file-manager-window").last
        note = window.locator(".fm-bin-note").inner_text()
        assert "30 days" in note and "10%" in note and "never within a day" in note
        row = window.locator(
            f".fm-row[data-path={json.dumps(mine['path'])}], .fm-grid-card[data-path={json.dumps(mine['path'])}]"
        ).first
        assert "restore-me.txt" in row.inner_text()  # the name it had, not the stored one
        acts = row.evaluate(
            "(r) => [...r.querySelectorAll('.fm-act-btn')].filter((b) => b.getClientRects().length).map((b) => b.dataset.act)"
        )
        assert "restore" in acts or "more-sheet" in acts, acts
        assert not {"download", "share", "rename"} & set(acts), acts
        if "restore" in acts:
            row.locator("[data-act=restore]").click()
        else:  # a phone: the row's "···" opens a sheet with Restore first
            row.locator("[data-act=more-sheet]").click()
            page.click(".sheet-action-item:has-text('Restore')")
        deadline = time.time() + 8
        while not os.path.exists(gone) and time.time() < deadline:
            time.sleep(0.3)
        assert os.path.exists(gone), "Restore did not bring the file back"
        browser.close()


def test_a_question_from_the_restore_window_can_be_answered():
    """SET-06: the restore window is a native modal window. Its "are you sure?" was drawn under
    it, dimmed and dead, and the window opened in the top-left corner. The backup behind it is
    played by the test: only the page is under test here."""
    from playwright.sync_api import sync_playwright

    asked = []
    state = {
        "repo": {"id": "old-nas", "name": "Old NAS", "location": "rclone:cloud:nas"},
        "versions": [{"time": "2026-11-01T02:00:00Z", "paths": ["/mnt/user/Photos"]}],
        "settings": [{"time": "2026-11-01T02:00:00Z"}],
    }

    def restore_settings(route):
        asked.append(route.request.headers.get("x-confirm-token") or "")
        route.fulfill(
            status=428,
            content_type="application/json",
            body=json.dumps(
                {
                    "error": "confirmation_required",
                    "detail": "Restore system settings from a backup, replacing the current ones. Confirm to continue.",
                    "action": "system.restore",
                    "target": "",
                    "summary": "Restore system settings from a backup, replacing the current ones",
                    "code": 428,
                }
            ),
        )

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.route(
            "**/api/offsite/connect-kit",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(state)),
        )
        # the card offers "Connect from a recovery kit" only where the backup tool is installed;
        # the machine that runs this test may not have it, and the page is what is under test
        page.route(
            "**/api/offsite",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"available": True, "repos": []})
            ),
        )
        page.route("**/api/offsite/repos/old-nas/restore-settings", restore_settings)
        _sign_in(page)
        _close_wizard(page)
        page.evaluate("() => window.openManagementWindow && window.openManagementWindow('mgmt-pane-backups')")
        page.click("[data-off=connect]", timeout=15000)
        page.wait_for_selector("dialog#restore-box[open]")
        box = page.locator("dialog#restore-box").bounding_box()
        assert box["x"] > 100 and box["y"] > 20, f"the restore window is not centred: {box}"
        assert abs((box["x"] + box["width"] / 2) - 720) < 30, box

        page.fill("#restorebox-kit", "a recovery kit")
        page.click("[data-rb=connect]")
        page.click("[data-rb=settings]")
        page.wait_for_selector("#confirm-toast-modal", state="visible", timeout=6000)
        assert (
            page.evaluate("() => document.getElementById('confirm-toast-modal').closest('dialog')?.id") == "restore-box"
        )
        # the answer can be given: this click timed out before, with the card under the window
        page.click("#confirm-toast-modal #confirm-toast-cancel", timeout=5000)
        page.wait_for_selector("#confirm-toast-modal", state="hidden", timeout=4000)
        assert asked == [""], "the settings were asked for once, and never confirmed"
        assert page.is_visible("dialog#restore-box [data-rb=settings]")  # the window is still there
        browser.close()


def test_shut_down_asks_and_the_card_follows_the_machine():
    """SET-07: "Shut down" ended the machine after two seconds, without a question. It now asks,
    only asks the system inside, and the card follows by itself: "Shutting down", and "Turn off
    now" once the server offers it. The machine is played by the test."""
    from playwright.sync_api import sync_playwright

    vm = {
        "id": "vm-j1",
        "name": "alpha",
        "state": "running",
        "vcpus": 2,
        "ram_gb": 2,
        "disk_size_gb": 20,
        "disk_format": "qcow2",
        "bridge": "br0",
        "os_family": "linux",
    }
    sent = []

    def action(route):
        act = json.loads(route.request.post_data or "{}").get("action")
        sent.append(act)
        if act == "stop":
            vm.update(state="shutting_down", turn_off_offered=False)
        elif act == "force_off":
            vm.update(state="stopped")
            vm.pop("turn_off_offered", None)
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps({"status": "ok", "state": vm["state"]})
        )

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.route(
            "**/api/vms",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps([vm])),
        )
        page.route("**/api/vms/vm-j1/action", action)
        _sign_in(page)
        _close_wizard(page)
        page.evaluate("() => window.openVmManager && window.openVmManager()")
        card = page.locator("[data-vm-id=vm-j1]")
        card.locator(".btn-vm-acpi").click(timeout=15000)
        page.wait_for_selector("#confirm-toast-modal", state="visible", timeout=6000)
        assert "alpha" in page.inner_text("#confirm-toast-modal")
        assert sent == [], "nothing is sent before the answer"
        page.click("#confirm-toast-modal #confirm-toast-ok")
        card.locator(".vm-shutting-note").wait_for(timeout=8000)
        assert sent == ["stop"]
        assert card.locator(".btn-vm-start").count() == 0  # a machine that shuts down is not "stopped"
        assert card.locator(".btn-vm-force-off").count() == 0  # and nothing ends it yet

        vm["turn_off_offered"] = True  # two minutes later, on the server's clock
        card.locator(".btn-vm-force-off").wait_for(timeout=12000)  # the card reads the list again by itself
        card.locator(".btn-vm-force-off").click()
        page.wait_for_selector("#confirm-toast-modal", state="visible", timeout=6000)
        assert sent == ["stop"]
        page.click("#confirm-toast-modal #confirm-toast-ok")
        card.locator(".btn-vm-start").wait_for(timeout=8000)
        assert sent == ["stop", "force_off"]
        browser.close()


def test_add_a_backup_job_opens_on_a_choice_that_works():
    """SET-06: the form's default was a choice the server always refused, and the passphrase field
    of a settings backup showed for a folder job (a style rule beat `hidden`)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        _sign_in(page)
        _close_wizard(page)
        page.evaluate("() => window.openManagementWindow && window.openManagementWindow('mgmt-pane-backups')")
        page.click("#btn-open-create-backup-job", timeout=15000)
        page.wait_for_selector("#create-backup-job-form", state="visible")
        assert page.input_value("#backup-job-dest-type") == "local_snapshot"
        assert not page.is_visible("#backup-job-passphrase")
        assert page.is_visible("#backup-dest-cloud-hint")
        shown = page.evaluate(
            "() => [...document.querySelectorAll('#backup-job-dest-type option')].filter((o) => !o.hidden).map((o) => o.value)"
        )
        assert shown == ["local_snapshot"], shown
        page.select_option("#backup-job-kind", "config")
        assert page.is_visible("#backup-job-passphrase")
        assert page.input_value("#backup-job-dest-type") == "local_folder"
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
        context.add_init_script("localStorage.setItem('kiboto_language', 'de')")
        page = context.new_page()
        page.goto(BASE + "/", wait_until="domcontentloaded", timeout=12000)
        page.wait_for_timeout(1500)
        for name, pane, root in GERMAN_SCREENS:
            if pane:
                if name == "people" and not page.evaluate("() => localStorage.getItem('kiboto_signed_in') === '1'"):
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


# SET-00: what a page hid must not be shown again by the phone layout
HIDDEN_BUT_SHOWN = """() => {
  const forced = '.btn-pill-toggle, .mgmt-inner-tab, .btn-container-act, .btn-locate-topo, .btn-webui-badge';
  const name = (el) => (el.id ? '#' + el.id : el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]);
  const shown = (el) => getComputedStyle(el).display !== 'none';
  const out = [...document.querySelectorAll('[hidden]')].filter(shown).map(name);
  for (const el of document.querySelectorAll(forced)) {
    if (el.style.display === 'none' && shown(el)) out.push(name(el) + ' (inline)');
  }
  return out;
}"""


def test_hidden_controls_stay_hidden_on_a_phone():
    from playwright.sync_api import sync_playwright

    found = {}
    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        _sign_in(page)
        _close_wizard(page)
        left = page.evaluate(HIDDEN_BUT_SHOWN)
        if left:
            found["launcher"] = left
        page.evaluate("() => window.openManagementWindow && window.openManagementWindow()")
        page.wait_for_selector("#management-window", state="attached", timeout=8000)
        count = page.evaluate("() => document.querySelectorAll('#management-window .mgmt-sidebar-item').length")
        assert count >= 8, "the Settings sidebar did not load"
        for i in range(count):
            label = page.evaluate(
                """(i) => { const el = document.querySelectorAll('#management-window .mgmt-sidebar-item')[i];
                  el.click(); return el.dataset.route || el.dataset.mgmtPane || el.dataset.mgmtTarget || el.dataset.mgmtAction || String(i); }""",
                i,
            )
            page.wait_for_timeout(900)
            left = page.evaluate(HIDDEN_BUT_SHOWN)
            if left:
                found[label] = left
        browser.close()
    assert not found, "hidden controls are shown at 390 px:\n" + json.dumps(found, indent=1)


# SET-12: Settings' own navigation, measured at the widths where it broke
SWITCH_IN_REACH = """() => {
  const side = document.querySelector('#management-window .mgmt-sidebar').getBoundingClientRect();
  const row = document.querySelector('.mgmt-advanced-row').getBoundingClientRect();
  const icon = document.querySelector('.mgmt-advanced-icon');
  return { inside: row.top >= side.top - 1 && row.bottom <= side.bottom + 1 && row.left >= side.left - 1 && row.right <= side.right + 1,
           width: Math.round(row.width), height: Math.round(row.height), icon: getComputedStyle(icon).display !== 'none',
           entries: document.querySelectorAll('#management-window .mgmt-sidebar-item:not([hidden])').length };
}"""
STRIP = """() => {
  const nav = document.querySelector('#management-window .mgmt-sidebar-nav');
  const seen = Array.from(nav.querySelectorAll('.mgmt-sidebar-item:not([hidden])'))
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right <= window.innerWidth + 1; });
  return { length: nav.scrollWidth, seen: seen.length, widest: Math.max(...seen.map((el) => Math.round(el.getBoundingClientRect().width))) };
}"""
SETTINGS_OPEN = """() => { const o = document.getElementById('management-modal-overlay');
  return !!o && o.classList.contains('open') && getComputedStyle(o).display !== 'none'; }"""


def _open_settings(page, advanced=True):
    page.evaluate("() => window.openManagementWindow()")
    page.wait_for_selector("#mgmt-advanced-switch", state="attached", timeout=8000)
    page.evaluate(
        "(on) => { const s = document.getElementById('mgmt-advanced-switch'); if (s.checked !== on) s.click(); }",
        advanced,
    )
    page.wait_for_timeout(500)


def test_settings_navigation_at_every_width():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        # a desktop: with Advanced on, the switch itself had scrolled out of the sidebar
        page = browser.new_context(viewport={"width": 1440, "height": 760}).new_page()
        _sign_in(page)
        _close_wizard(page)
        _open_settings(page)
        wide = page.evaluate(SWITCH_IN_REACH)
        assert wide["inside"] and wide["entries"] >= 12, f"the Advanced switch is out of reach on a desktop: {wide}"
        assert not wide["icon"], "the full sidebar shows the switch with its name, not the icon"
        page.context.close()

        # the icon rail: the switch was a bare 13 px checkbox
        page = browser.new_context(viewport={"width": 900, "height": 760}).new_page()
        _sign_in(page)
        _close_wizard(page)
        _open_settings(page)
        rail = page.evaluate(SWITCH_IN_REACH)
        assert rail["inside"] and rail["icon"] and rail["width"] >= 40 and rail["height"] >= 40, (
            f"on the icon rail the Advanced switch is not a button of its own: {rail}"
        )
        page.context.close()

        # the strip: every entry kept the desktop's full width, so only "Overview" showed
        page = browser.new_context(viewport={"width": 700, "height": 800}).new_page()
        _sign_in(page)
        _close_wizard(page)
        _open_settings(page)
        strip = page.evaluate(STRIP)
        assert strip["seen"] >= 4 and strip["widest"] < 260 and strip["length"] < 2600, (
            f"the navigation strip at 700 px shows too little: {strip}"
        )
        page.context.close()

        # a phone: the browser's Back closes Settings
        page = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        _sign_in(page)
        _close_wizard(page)
        page.evaluate("() => window.openManagementWindow()")
        page.wait_for_function(SETTINGS_OPEN, timeout=8000)
        page.wait_for_timeout(600)  # the shell adds its history entry once the page is open
        page.go_back()
        page.wait_for_timeout(900)
        assert not page.evaluate(SETTINGS_OPEN), "the phone's Back left Settings open"
        browser.close()


# NPERF-5: what a fresh browser downloads, as the bytes on the wire (compressed, headers too). A
# fresh install measured 382 kB for the sign-in page and 337 kB in the 10 s after signing in
# (3 Nov 2026, after the icon sprite was answered with 304 and the chassis photos were resized).
SIGN_IN_PAGE_KB = 450
FIRST_10S_KB = 420


def test_the_first_seconds_stay_within_their_byte_budget():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _browser(p)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        done = []
        page.on("requestfinished", lambda r: done.append((time.time(), r)))
        page.goto(BASE + "/", wait_until="load", timeout=30000)
        page.wait_for_timeout(1500)
        sign_in = list(done)
        start = time.time()
        _sign_in_with_keyboard(page)
        page.wait_for_timeout(max(0, 10000 - int((time.time() - start) * 1000)))

        def size(r):
            s = r.sizes()
            return s["responseBodySize"] + s["responseHeadersSize"]

        after = [r for t, r in done[len(sign_in) :] if t - start <= 10]
        first_kb = sum(size(r) for _, r in sign_in) / 1000
        after_kb = sum(size(r) for r in after) / 1000
        biggest = sorted(((size(r), r.url.replace(BASE, "")) for r in after), reverse=True)[:5]
        browser.close()
    assert first_kb <= SIGN_IN_PAGE_KB, f"the sign-in page downloads {first_kb:.0f} kB (budget {SIGN_IN_PAGE_KB})"
    assert after_kb <= FIRST_10S_KB, (
        f"{after_kb:.0f} kB in the 10 s after signing in (budget {FIRST_10S_KB}): {biggest}"
    )
