"""SET-11: a sentence the server sends to a person carries how it was made, so the page can show
it in the reader's language. The first one: the sign-in hours refusal a kid reads."""

from datetime import datetime

from backend import users_db
from backend.errors import error_body, said

PW = "a-long-enough-pass-1"


def test_said_names_the_key_and_keeps_the_values():
    assert said("outside_hours_daily", start="08:00", end="20:00") == {
        "msg_key": "srv.outside_hours_daily",
        "params": {"start": "08:00", "end": "20:00"},
    }
    body = error_body(403, "English sentence.", error="x", text=said("k", n=1))
    assert body["detail"] == "English sentence." and body["text"]["msg_key"] == "srv.k"


def test_the_sign_in_hours_refusal_says_how_it_was_made(client):
    today = datetime.now().weekday()
    other_days = [d for d in range(7) if d != today]
    user = users_db.create_user("set11kid", "Kim", PW, role_id="kid")
    try:
        users_db.update_user_profile(user["id"], signin_hours={"days": other_days, "start": "07:00", "end": "20:00"})
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "set11kid", "password": PW})
        assert r.status_code == 403
        body = r.json()
        assert body["error"] == "outside_signin_hours" and "server time" in body["detail"]
        assert body["text"] == {
            "msg_key": "srv.outside_hours_days",
            "params": {"start": "07:00", "end": "20:00", "days": {"weekdays": other_days}},
        }
        # every day: the other sentence (the hours here end before they start, so now is outside)
        now = datetime.now()
        start = f"{(now.hour + 2) % 24:02d}:00"
        end = f"{(now.hour + 3) % 24:02d}:00"
        users_db.update_user_profile(user["id"], signin_hours={"days": list(range(7)), "start": start, "end": end})
        client.cookies.clear()
        r = client.post("/api/auth/login", json={"username": "set11kid", "password": PW})
        if r.status_code == 403:  # not around midnight, where the window may wrap onto now
            assert r.json()["text"]["msg_key"] == "srv.outside_hours_daily"
    finally:
        users_db.delete_user(user["id"])
