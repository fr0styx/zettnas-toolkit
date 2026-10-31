"""NAI-17: the eval scores answers strictly: a refusal opens a sentence and guesses no fact, and
a right fact beside a rival one doesn't pass."""

from tests.rag_eval.run_eval import answer_matches, says_not_found


def test_a_refusal_opens_a_sentence():
    assert says_not_found("I couldn't find that in your files.")
    assert says_not_found("Leider: Das steht nicht in deinen Dateien.")
    assert says_not_found("没有找到相关内容。")
    assert not says_not_found(
        "The boiler was serviced last year, so the warranty is not in effect any more because the installer never registered it."
    )


def test_a_refusal_with_a_guess_is_not_one():
    assert not says_not_found("I couldn't find it, but it was probably 2019.")
    assert not says_not_found("")


def test_a_right_fact_beside_a_rival_does_not_pass():
    assert answer_matches("The limit is 185 kg.", ["185 kg"])
    assert not answer_matches("It is 185 kg or maybe 190 kg.", ["185 kg"])
    assert answer_matches(
        "It was paid on 12 March 2025: 185 kg of pellets.", ["185 kg"]
    )  # other kinds of number are fine
    assert not answer_matches("Nothing about that.", ["185 kg"])
    assert answer_matches("Bring the red folder and 2 photos.", ["red folder"], ["2 photos"])
    assert not answer_matches("Bring the red folder.", ["red folder"], ["2 photos"])
    assert answer_matches("Anything.", [])
