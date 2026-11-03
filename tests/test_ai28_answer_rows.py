"""AI-28: the eval can write every answer as the person saw it, for people to label."""

import json
import sys

from tests.rag_eval import run_eval


def test_answers_out_writes_every_answer_and_keeps_them_out_of_the_result(tmp_path, monkeypatch, capsys):
    rows = [{"id": "qa-001", "question": "Q?", "answer": "A.", "sources": ["en/a.md"], "auto_correct": True}]
    monkeypatch.setattr(
        run_eval,
        "evaluate",
        lambda *a, **k: {"overall": {}, "misses": [], "answers": {"wrong": []}, "answer_rows": list(rows)},
    )
    out, rows_file = tmp_path / "r.json", tmp_path / "rows.json"
    monkeypatch.setattr(sys, "argv", ["run_eval", "--answers", "m", "--out", str(out), "--answers-out", str(rows_file)])
    run_eval.main()
    assert json.loads(rows_file.read_text()) == rows
    assert "answer_rows" not in json.loads(out.read_text())
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["run_eval", "--answers", "m"])
    run_eval.main()  # without --answers-out the rows are dropped
    assert "answer_rows" not in capsys.readouterr().out
