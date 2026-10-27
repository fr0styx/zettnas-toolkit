"""Back up my phone (B8): the Immich card's state, and its line in Getting started."""

from backend.services import getting_started
from backend.services import immich_photos as im


def test_each_person_marks_their_own_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "CONFIG_FILE", str(tmp_path / "immich.json"))
    monkeypatch.setattr(im, "detect", lambda: "")
    assert im.status("lea")["phone_done"] is False and im.status("lea")["sso"] is False
    im.set_phone_done("lea", True)
    assert im.status("lea")["phone_done"] and not im.status("dad")["phone_done"]
    im.set_phone_done("lea", False)
    assert not im.phone_done("lea")
    im.set_sso(True)
    assert im.status("dad")["sso"] is True


def test_getting_started_asks_everyone_to_back_up_their_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(im, "CONFIG_FILE", str(tmp_path / "immich.json"))
    for name in ("_password_changed", "_has_share", "_has_app", "_has_backup", "_alerts_set_up", "_ai_has_files"):
        monkeypatch.setattr(getting_started, name, lambda: True)
    monkeypatch.setattr(getting_started, "_host_managed", lambda: "")
    monkeypatch.setattr(getting_started, "_two_factor", lambda u: True)
    kid = {r["id"]: r for r in getting_started.checklist("lea", is_admin=False)["items"]}
    assert set(kid) == {"password", "two_factor", "phone_backup"}  # the rest is the owner's job
    assert kid["phone_backup"]["done"] is False and kid["phone_backup"]["open"] == "mgmt-pane-backups"
    im.set_phone_done("lea", True)
    assert getting_started.checklist("lea", is_admin=False)["complete"]


def test_the_api_marks_it():
    from backend.api import immich as api
    from backend.auth import AuthenticatedPrincipal

    me = AuthenticatedPrincipal(user_id="u1", username="phone_tester", role_id="share_user", scopes=[])
    assert api.put_phone(api.PhoneIn(done=True), me) == {"done": True}
    assert api.get_status(me)["phone_done"] is True
    api.put_phone(api.PhoneIn(done=False), me)
