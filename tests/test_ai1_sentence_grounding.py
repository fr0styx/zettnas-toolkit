"""AI-1: grounding is scored on the final answer, sentence by sentence."""

from backend.services.rag_grounding import score_answer_grounding

SRC = [
    {
        "name": "banana_bread.md",
        "excerpt": "Pour into a greased loaf tin and bake at 175 °C for 55–60 minutes, until a skewer comes out clean.",
    },
    {
        "name": "inspektion_golf.txt",
        "excerpt": "Letzte Inspektion: 3. Juni bei Autohaus Brandl. Rechnung 612,40 Euro, per Überweisung bezahlt.",
    },
]


def test_supported_and_invented_sentences():
    answer = "Bake the loaf at 175 °C for 55 to 60 minutes [1]. Then add 300 g of chocolate on top."
    res = score_answer_grounding(answer, SRC)
    assert res["total"] == 2 and res["supported"] == 1 and res["score"] == 50
    assert res["sentences"][0]["supported"] and res["sentences"][0]["source"] == 1
    assert not res["sentences"][1]["supported"]


def test_a_wrong_number_is_not_supported_even_with_shared_words():
    res = score_answer_grounding("Bake the loaf at 200 °C until a skewer comes out clean.", SRC)
    assert res["supported"] == 0


def test_numbers_in_other_formats_still_match():
    res = score_answer_grounding("Die Inspektion hat 612.40 Euro gekostet.", SRC)
    assert res["supported"] == 1


def test_cross_language_answers_count_with_a_neural_embedder():
    # an English answer about the German file: no shared words, same meaning
    vec = {"golf": [1.0, 0.0], "other": [0.0, 1.0]}
    embed = lambda text: vec["golf"] if ("Inspektion" in text or "inspection" in text) else vec["other"]  # noqa: E731
    res = score_answer_grounding("The last car inspection cost 612.40 euros.", SRC, embed=embed)
    assert res["method"] == "neural" and res["supported"] == 1


def test_nothing_to_score():
    assert score_answer_grounding("Sure!", SRC) is None
    assert score_answer_grounding("Bake at 175 °C for an hour.", []) is None
    res = score_answer_grounding("I couldn't find that in your files. Bake at 175 °C for 55 minutes.", SRC)
    assert res["total"] == 1
