"""A first-ever scoring run must agree with the rescore that follows it (the verifier found 40 rows flipping)."""
from pipeline.run import main

from pipeline_util import make_db
from test_pipeline_score import seed


def test_all_then_rescore_changes_nothing(tmp_path, monkeypatch, capsys):
    db = make_db(tmp_path, monkeypatch)
    seed(db)
    assert main(["all", "--no-phash"]) == 0
    before = db.query("SELECT listing_id, tier, deal_label, sort_key FROM feed ORDER BY listing_id")
    capsys.readouterr()
    assert main(["rescore", "--no-phash"]) == 0
    assert db.query("SELECT listing_id, tier, deal_label, sort_key FROM feed ORDER BY listing_id") == before
