"""NAI-18: the answer scoring reads the shipped model's answers as a person would: citation chips
are not facts, and a refusal that names the files counts wherever it stands."""

from tests.rag_eval.run_eval import answer_matches, says_not_found


def test_citation_chips_are_not_rival_numbers():
    assert answer_matches("Three very ripe bananas go in the banana bread [1].", ["three", "3"])
    assert answer_matches("The JR Pass should be activated on 7 April [1].", ["7 April"])
    assert answer_matches("It needs its next vaccination on 2026-03-02 [1][2].", ["2026-03-02"])
    assert answer_matches("Six eggs, see 【1】.", ["six", "6"])
    assert not answer_matches("It is 185 kg [1] or maybe 190 kg [2].", ["185 kg"])  # still a rival


def test_a_refusal_naming_the_files_counts_where_it_stands():
    assert says_not_found(
        "The information about the Lisbon trip in 2024 and the hotel booked is not in the indexed files.",
        "Which hotel did we book for the Lisbon trip in 2024?",
    )
    assert says_not_found(
        "Die Kundennummer meines Stromanbieters ist nicht in den bereitgestellten Dokumenten angegeben."
    )
    assert says_not_found("Le numéro de votre passeport n'est pas mentionné dans les documents indexés.")
    assert says_not_found("Il n'est pas possible de déterminer le coût de l'abonnement à partir des documents indexés.")
    assert says_not_found("No se menciona en los documentos proporcionados el código del portal.")
    assert says_not_found("我无法提供您家的无线网络密码，因为该信息未在提供的文件中提及。")


def test_a_claim_before_the_refusal_or_a_guess_still_fails():
    assert not says_not_found("The licence plate of your car is M-KL 4821 [1].")
    assert not says_not_found("El seguro del coche vence el 3 de junio. [3]")
    assert not says_not_found(
        "Die Garantie meines Fernsehers läuft nicht ab, da die Informationen in den Dokumenten nicht erwähnt werden [1]."
    )
    assert not says_not_found(
        "The boiler was serviced last year, so the warranty is not in effect because the installer never registered it."
    )
    assert not says_not_found("The trip in 2024 is not in the files, but it was probably in 2023.", "the trip in 2024")
