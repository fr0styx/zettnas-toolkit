"""B13 (AI-24): a photo's EXIF date and GPS position (HEIC too) are read as it is indexed, named
offline from the place list, and become filters; older photos are read at night on awake disks
only; the chat sees each photo's caption, date and place."""

import calendar
import gzip
import sqlite3
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.services import photo_place
from backend.services.rag_engine import RagSearchEngine

PLACES = [
    ("Rome", "Lazio", "Italy", 41.89193, 12.51133),
    ("Tivoli", "Lazio", "Italy", 41.95952, 12.80160),
    ("Paris", "Île-de-France", "France", 48.85341, 2.3488),
    ("New York City", "New York", "United States", 40.71427, -74.00597),
    ("York", "England", "United Kingdom", 53.95763, -1.08271),
    ("Fiji Town", "", "Fiji", -17.8, 179.9),
]


@pytest.fixture(autouse=True)
def places(tmp_path):
    p = tmp_path / "places.tsv.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        for row in PLACES:
            fh.write("\t".join(str(x) for x in row) + "\n")
    photo_place.use_places(str(p))
    yield p
    photo_place.use_places(None)


def _photo(path, taken="2023:06:01 23:30:12", gps=((41, 54, 7.2), "N", (12, 29, 0), "E"), fmt="JPEG"):
    img = Image.new("RGB", (64, 48), (200, 120, 40))
    exif = Image.Exif()
    if taken:
        exif[0x0132] = taken
        exif.get_ifd(0x8769)[0x9003] = taken
    if gps:
        g = exif.get_ifd(0x8825)
        g[1], g[2], g[3], g[4] = gps[1], tuple(float(x) for x in gps[0]), gps[3], tuple(float(x) for x in gps[2])
    img.save(path, fmt, exif=exif)
    return path


def test_the_capture_date_is_the_cameras_clock():
    assert photo_place.taken_epoch("2023:06:01 23:30:12") == calendar.timegm((2023, 6, 1, 23, 30, 12, 0, 0, 0))
    assert photo_place.taken_epoch("0000:00:00 00:00:00") is None
    assert photo_place.taken_epoch("") is None
    assert photo_place.when_label(photo_place.taken_epoch("2023:06:01 23:30:12")) == "June 2023"
    assert photo_place.when_label(None) == ""


def test_date_and_position_from_a_jpeg(tmp_path):
    taken, lat, lon = photo_place.when_where(str(_photo(tmp_path / "a.jpg")))
    assert taken == calendar.timegm((2023, 6, 1, 23, 30, 12, 0, 0, 0))
    assert lat == pytest.approx(41.902, abs=1e-3) and lon == pytest.approx(12.4833, abs=1e-3)
    # south and west are negative; 0,0 is a camera without a fix
    _t, lat, lon = photo_place.when_where(str(_photo(tmp_path / "b.jpg", gps=((33, 52, 0), "S", (151, 12, 0), "W"))))
    assert lat < 0 and lon < 0
    assert photo_place.when_where(str(_photo(tmp_path / "c.jpg", gps=((0, 0, 0), "N", (0, 0, 0), "E"))))[1:] == (
        None,
        None,
    )
    assert photo_place.when_where(str(_photo(tmp_path / "d.jpg", taken=None, gps=None))) == (None, None, None)
    assert photo_place.when_where(str(tmp_path / "e.gif")) == (None, None, None)  # no EXIF kind
    (tmp_path / "f.jpg").write_bytes(b"not a photo")
    assert photo_place.when_where(str(tmp_path / "f.jpg")) == (None, None, None)
    data = _photo(tmp_path / "g.jpg").read_bytes()
    assert photo_place.when_where(data, "g.jpg")[0] is not None


def test_heic_photos_are_read_too(tmp_path):
    photo_place.ensure_heif()
    path = tmp_path / "IMG_0001.heic"
    try:
        _photo(path, fmt="HEIF")
    except Exception:
        pytest.skip("this pillow-heif cannot write HEIC")
    taken, lat, _lon = photo_place.when_where(str(path))
    assert taken is not None and lat == pytest.approx(41.902, abs=1e-3)


def test_the_nearest_town_names_the_position():
    assert photo_place.place_for(41.902, 12.483) == "Rome, Lazio, Italy"
    assert photo_place.place_for(41.96, 12.79) == "Tivoli, Lazio, Italy"
    assert photo_place.place_for(-17.8, -179.95) == "Fiji Town, Fiji"  # across the date line
    assert photo_place.place_for(0.0, -30.0) == ""  # the middle of the ocean
    assert photo_place.place_for(None, 12.0) == ""
    photo_place.use_places(None)
    photo_place.PLACES_FILE, old = "/nowhere/places.tsv.gz", photo_place.PLACES_FILE
    try:
        assert photo_place.place_for(41.902, 12.483) == ""  # no list: no name, nothing online
    finally:
        photo_place.PLACES_FILE = old
        photo_place.use_places(None)


T0 = calendar.timegm((2026, 10, 1, 0, 0, 0, 0, 0, 0))


def _span(y1, m1, y2, m2):
    return photo_place._span(y1, m1, y2, m2)


@pytest.mark.parametrize(
    ("question", "want"),
    [
        ("photos from June 2023", (*_span(2023, 6, 2023, 6), "2023-06")),
        ("Fotos vom Juni 2023", (*_span(2023, 6, 2023, 6), "2023-06")),
        ("photos de juillet 2022", (*_span(2022, 7, 2022, 7), "2022-07")),
        ("fotos de agosto de 2021", (*_span(2021, 8, 2021, 8), "2021-08")),
        ("2023年6月的照片", (*_span(2023, 6, 2023, 6), "2023-06")),
        ("pictures from summer 2022", (*_span(2022, 6, 2022, 8), "2022-summer")),
        ("Bilder vom Winter 2023", (*_span(2023, 12, 2024, 2), "2023-winter")),
        ("photos from 2019", (*_span(2019, 1, 2019, 12), "2019")),
        ("photos from last year", (*_span(2025, 1, 2025, 12), "2025")),
        ("去年的照片", (*_span(2025, 1, 2025, 12), "2025")),
        ("photos from May 2024", (*_span(2024, 5, 2024, 5), "2024-05")),
        ("may I see the 2024 photos", (*_span(2024, 1, 2024, 12), "2024")),  # "may" is not May here
        ("photos from 2019 and 2020", None),
        ("beach photos", None),
    ],
)
def test_the_time_a_question_names(question, want):
    assert photo_place.when_in_question(question, now=T0) == want


def test_filter_chips_and_the_places_a_question_names():
    assert photo_place.span_for("2023") == _span(2023, 1, 2023, 12)
    assert photo_place.span_for("2023-06") == _span(2023, 6, 2023, 6)
    assert (
        photo_place.span_for("2023-13") is None
        and photo_place.span_for("soon") is None
        and photo_place.span_for(None) is None
    )
    labels = ["Rome, Lazio, Italy", "New York City, New York, United States", "York, England, United Kingdom"]
    assert photo_place.place_in_question("photos from Rome", labels) == "Rome"
    assert photo_place.place_in_question("pictures of new york city at night", labels) == "New York City"
    assert photo_place.place_in_question("our trip to York", labels) == "York"
    assert photo_place.place_in_question("photos from Italy", labels) == "Italy"
    assert photo_place.place_in_question("romantic dinner photos", labels) is None
    assert photo_place.asks_for_photos("Fotos vom Strand") and photo_place.asks_for_photos("2023年的照片")
    assert not photo_place.asks_for_photos("tax return 2023")


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    _photo(root / "rome.jpg")
    _photo(root / "paris.jpg", taken="2022:04:10 10:00:00", gps=((48, 51, 12), "N", (2, 21, 0), "E"))
    _photo(root / "nodate.jpg", taken=None, gps=None)
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    yield engine, root, tmp_path
    engine.close()


def _photos(tmp_path):
    conn = sqlite3.connect(tmp_path / "rag.db")
    conn.row_factory = sqlite3.Row
    try:
        return {r["file_name"]: dict(r) for r in conn.execute("SELECT * FROM photo_assets")}
    finally:
        conn.close()


def test_indexing_reads_when_and_where(library):
    _engine, _root, tmp = library
    rows = _photos(tmp)
    assert rows["rome.jpg"]["location_label"] == "Rome, Lazio, Italy"
    assert rows["rome.jpg"]["taken_at"] == calendar.timegm((2023, 6, 1, 23, 30, 12, 0, 0, 0))
    assert "taken June 2023 in Rome, Lazio, Italy" in rows["rome.jpg"]["caption_text"]
    assert rows["paris.jpg"]["location_label"].startswith("Paris")
    assert rows["nodate.jpg"]["taken_at"] is None and rows["nodate.jpg"]["location_label"] == ""
    assert {r["when_where_done"] for r in rows.values()} == {1}


def _names(res):
    return sorted(p["name"] for p in res.get("photo_results") or res.get("photos") or [])


def test_search_filters_photos_by_date_and_place(library):
    engine, _root, _tmp = library
    assert _names(engine.search(query="", mode="photos", taken="2023")) == ["rome.jpg"]
    assert _names(engine.search(query="", mode="photos", place="Paris")) == ["paris.jpg"]
    assert _names(engine.search(query="", mode="photos", taken="2023-06", place="Paris")) == []
    # a question about photos filters by itself
    res = engine.search(query="photos from Rome in June 2023")
    assert _names(res) == ["rome.jpg"]
    hit = (res.get("photo_results") or res.get("photos"))[0]
    assert hit["taken"] == "2023-06-01" and hit["place"] == "Rome, Lazio, Italy" and "June 2023" in hit["caption"]
    # a question about papers is not filtered: "tax 2023" leaves the photos alone
    assert engine._photo_filters("tax return 2023", "all", None, None) == (None, None)


def test_the_photo_filter_chips(library):
    engine, _root, _tmp = library
    facets = engine.photo_facets()
    assert facets["years"] == [{"value": "2023", "count": 1}, {"value": "2022", "count": 1}]
    assert {p["value"] for p in facets["places"]} == {"Rome, Lazio, Italy", "Paris, Île-de-France, France"}


def test_older_photos_are_read_at_night_on_awake_disks_only(library, monkeypatch):
    engine, _root, tmp = library
    conn = sqlite3.connect(tmp / "rag.db")
    conn.execute("UPDATE photo_assets SET taken_at = NULL, location_label = '', when_where_done = 0")
    conn.commit()
    assert photo_place.backfill(conn, lambda dev, path: False) == (0, 3)  # all asleep: nothing read
    assert photo_place.backfill(conn, lambda dev, path: "rome" in path) == (1, 2)
    conn.commit()
    conn.close()
    assert _photos(tmp)["rome.jpg"]["location_label"] == "Rome, Lazio, Italy"

    from backend.services import ai_activity
    from backend.services import rag_engine_learning as learning

    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: False)
    engine._maybe_backfill_photo_dates()
    assert _photos(tmp)["paris.jpg"]["when_where_done"] == 0  # not by day
    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: True)
    monkeypatch.setattr(learning.rag_standby, "is_backing_disk_in_standby", lambda dev: False)
    engine._maybe_backfill_photo_dates()
    rows = _photos(tmp)
    assert rows["paris.jpg"]["location_label"].startswith("Paris") and {
        r["when_where_done"] for r in rows.values()
    } == {1}
    engine._maybe_backfill_photo_dates()
    assert engine._photo_dates_done is True


def test_a_vanished_photo_is_marked_read(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, canonical_path TEXT, backing_dev TEXT, parse_status TEXT)"
    )
    conn.execute(
        "CREATE TABLE photo_assets (file_id INTEGER PRIMARY KEY, caption_text TEXT, taken_at REAL, gps_lat REAL, "
        "gps_lon REAL, location_label TEXT, when_where_done INTEGER)"
    )
    conn.execute("INSERT INTO indexed_files VALUES (1, ?, '', 'ok')", (str(tmp_path / "gone.jpg"),))
    conn.execute("INSERT INTO photo_assets VALUES (1, 'Photo', NULL, NULL, NULL, '', 0)")
    assert photo_place.backfill(conn, lambda d, p: True) == (1, 0)
    assert conn.execute("SELECT when_where_done FROM photo_assets").fetchone()[0] == 1


def test_the_chat_sees_caption_date_and_place(monkeypatch):
    from backend.services import chat_nas_tools

    photo = {
        "file_id": 7, "name": "rome.jpg", "path": "/mnt/user/photos/rome.jpg", "thumbnail_url": "/t/7",
        "caption": "Photo featuring outdoor, taken June 2023 in Rome, Lazio, Italy", "taken": "2023-06-01",
        "place": "Rome, Lazio, Italy",
    }  # fmt: skip

    class Rag:
        def get_config(self):
            return {}

        def ask(self, **kw):
            return {"citations": [], "photos": [photo]}

    monkeypatch.setattr(chat_nas_tools, "_core", lambda: SimpleNamespace(get_rag_engine=lambda: Rag()))
    out = chat_nas_tools.tool_search_nas_knowledge("photos from Rome")
    got = out["photos"][0]
    assert got["taken"] == "2023-06-01" and got["place"] == "Rome, Lazio, Italy" and "June 2023" in got["caption"]


def test_the_photo_facets_route(client, auth_headers, monkeypatch):
    class Engine:
        def photo_facets(self, principal):
            return {"years": [{"value": "2023", "count": 2}], "places": []}

    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: Engine())
    res = client.get("/api/ai/photo-facets", headers=auth_headers)
    assert res.status_code == 200 and res.json()["years"][0]["value"] == "2023"


def test_the_place_list_builder(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_places", "scripts/build_places.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "cities.txt").write_text(
        "3169070\tRome\tRome\t\t41.89193\t12.51133\tP\tPPLC\tIT\t\t07\t\t\t\t2318895\t\t20\tEurope/Rome\t2024-01-01\n"
        "short line\n",
        encoding="utf-8",
    )
    (tmp_path / "admin1.txt").write_text("IT.07\tLazio\tLazio\t3174976\n", encoding="utf-8")
    (tmp_path / "countries.txt").write_text("# comment\nIT\tITA\t380\tIT\tItaly\tRome\n", encoding="utf-8")
    out = tmp_path / "places.tsv.gz"
    assert (
        mod.build(str(tmp_path / "cities.txt"), str(tmp_path / "admin1.txt"), str(tmp_path / "countries.txt"), str(out))
        == 1
    )
    photo_place.use_places(str(out))
    try:
        assert photo_place.place_for(41.9, 12.5) == "Rome, Lazio, Italy"
    finally:
        photo_place.use_places(None)


def test_the_shipped_place_list_names_real_places():
    import os

    assert os.path.isfile(photo_place.PLACES_FILE) and os.path.getsize(photo_place.PLACES_FILE) < 2_000_000
    photo_place.use_places(None)
    try:
        assert photo_place.place_for(41.902, 12.483) == "Rome, Lazio, Italy"
        assert photo_place.place_for(48.857, 2.352).startswith("Paris")
        assert photo_place.place_for(25.04, 102.72) == "Kunming, Yunnan, China"
        assert photo_place.place_for(0.0, -30.0) == ""  # the Atlantic
        assert photo_place.place_for(41.9022, 12.4539).startswith("Vatican")  # St Peter's Square
        assert photo_place.place_for(48.8352, 2.2410).startswith("Boulogne")  # a suburb keeps its name
    finally:
        photo_place.use_places(None)


def test_photos_read_before_the_place_list_get_named_from_the_index(library):
    engine, _root, tmp = library
    conn = sqlite3.connect(tmp / "rag.db")
    conn.execute("UPDATE photo_assets SET location_label = '' WHERE gps_lat IS NOT NULL")
    conn.execute("DELETE FROM rag_meta WHERE key = 'photo_places'")
    conn.commit()
    conn.close()
    engine._places_named_for = ""
    engine._places_cursor = 0
    engine._maybe_name_photo_places()  # one batch: both photos
    rows = _photos(tmp)
    assert rows["rome.jpg"]["location_label"] == "Rome, Lazio, Italy" and "in Rome" in rows["rome.jpg"]["caption_text"]
    assert rows["paris.jpg"]["location_label"].startswith("Paris")
    engine._maybe_name_photo_places()  # nothing left: the list is marked done
    assert engine._places_named_for == photo_place.places_signature() != ""
    engine._maybe_name_photo_places()  # and is not looked at again
