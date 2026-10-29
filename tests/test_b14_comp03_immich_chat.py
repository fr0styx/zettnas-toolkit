"""B14 COMP-03: photo questions in chat also get the person's Immich photos."""

from types import SimpleNamespace

import pytest

from backend.services import ai_chat_agent as agent


@pytest.mark.parametrize(
    "text",
    [
        "Show me photos of the beach",
        "fotos vom urlaub",
        "¿tienes imágenes del perro?",
        "我的猫的照片",
        "Bilder aus Rom",
    ],
)
def test_photo_questions_in_every_ui_language(text):
    assert agent.is_photo_question(text.lower())


@pytest.mark.parametrize("text", ["what is my disk temperature", "photosynthesis in my notes", "imagine a garden"])
def test_other_questions_are_not(text):
    assert not agent.is_photo_question(text.lower())


def test_immich_is_asked_for_photo_questions_only(monkeypatch):
    asked = []

    def search(username, query, limit):
        asked.append((username, query, limit))
        return [{"id": "a1", "source": "immich"}]

    monkeypatch.setattr("backend.services.immich_photos.smart_search", search)
    who = SimpleNamespace(username="ana")
    assert agent.immich_photos_for("photos of the beach", "photos of the beach", who) == [
        {"id": "a1", "source": "immich"}
    ]
    assert asked == [("ana", "photos of the beach", 12)]
    assert agent.immich_photos_for("disk temps", "disk temps", who) == []
    assert len(asked) == 1


def test_an_immich_failure_never_breaks_the_reply(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("immich down")

    monkeypatch.setattr("backend.services.immich_photos.smart_search", boom)
    assert agent.immich_photos_for("my photos", "my photos", SimpleNamespace(username="ana")) == []
