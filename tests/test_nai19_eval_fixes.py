"""NAI-19: two answers the nightly eval scored wrong were the eval's mistakes."""

import json
from pathlib import Path

from tests.rag_eval.run_eval import answer_matches, says_not_found

CORPUS = Path(__file__).parent / "rag_eval" / "corpus"


def test_a_next_step_with_its_own_number_is_not_a_rival():
    answer = (
        "Boiler fault F22 means the pressure has dropped below 0.8 bar when cold [1]. To repressurise, "
        "open the filling loop slowly until the gauge reads 1.2 bar, then close both valves [1]."
    )
    assert answer_matches(answer, ["pressure"], ["pressure", "0.8"])
    assert answer_matches(answer, ["0.8"])


def test_a_rival_in_the_same_sentence_still_fails():
    assert not answer_matches("It weighs 185 or 190 kg.", ["185"])
    assert not answer_matches(
        "Les frais de garde déclarés sont de 52 400 €, ce qui inclut 3 200 € pour la crèche [1].", ["3200", "3 200"]
    )
    assert answer_matches("Les frais de garde déclarés sont de 3 200 € [1]. Les salaires : 52 400 €.", ["3 200"])


def test_an_unanswerable_question_is_really_unanswerable():
    qa = {q["id"]: q for q in json.loads((Path(__file__).parent / "rag_eval" / "qa.json").read_text())}
    q = qa["qa-098"]
    assert q["unanswerable"] and "VIN" in q["question"]
    text = " ".join(p.read_text(errors="ignore") for p in CORPUS.rglob("*") if p.is_file())
    assert "M-KL 4821" in text  # the plate is in the corpus, which is why the old question had an answer
    assert " VIN" not in text and "Fahrgestellnummer" not in text


def test_the_gym_question_has_its_answer_in_the_spanish_expenses():
    """qa-103 was labelled unanswerable, but the monthly expenses list the gym at 39 (gimnasio)."""
    qa = {q["id"]: q for q in json.loads((Path(__file__).parent / "rag_eval" / "qa.json").read_text())}
    q = qa["qa-103"]
    assert not q["unanswerable"] and q["answer_any"] == ["39"]
    (doc,) = q["relevant"]
    assert "gimnasio,39" in (CORPUS / doc).read_text()


def test_a_gym_question_the_files_cannot_answer_keeps_ten_refusals():
    """qa-108 keeps the gym as a distractor: the expenses list it, but not when it closes."""
    qa = json.loads((Path(__file__).parent / "rag_eval" / "qa.json").read_text())
    by_id = {q["id"]: q for q in qa}
    assert by_id["qa-108"]["unanswerable"] and sum(1 for q in qa if q.get("unanswerable")) == 10


def test_more_ways_of_saying_the_files_do_not_say_count_as_a_refusal():
    """NAI-20: three right refusals were scored as guesses."""
    assert says_not_found("The VIN of your car is not provided in the given documents.", "What is the VIN of my car?")
    assert says_not_found(
        "The documents do not mention a hotel booked for a Lisbon trip in 2024.",
        "Which hotel did we book for the Lisbon trip in 2024?",
    )
    assert says_not_found("我们家的无线网络密码没有在提供的文件中提及。", "我们家的无线网络密码是什么？")
    # still a guess: a date of its own beside the phrase, or a claim
    assert not says_not_found("The documents do not mention it, but it is probably 2027.", "When does it expire?")
    assert not says_not_found("Die Garantie meines Fernsehers läuft im Jahr 2027 ab.", "Wann läuft die Garantie ab?")
