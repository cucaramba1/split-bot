from splitbot.db import DB
from splitbot.money import Transfer

PAYLOAD = {"payer": "Некит",
           "items": [{"title": "кофе", "amount": 120000, "split": ["Некит", "Антон", "Полина"]}],
           "turns": [{"queue": "water", "who": "Некит"}]}


def mk(tmp_path):
    return DB(tmp_path / "t.db")


def test_members_unique(tmp_path):
    db = mk(tmp_path)
    assert db.add_member(1, "Некит") is True
    assert db.add_member(2, "Некит") is False
    assert db.add_member(1, "Антон") is False
    assert db.member_name(1) == "Некит"


def test_save_once(tmp_path):
    db = mk(tmp_path)
    d = db.create_draft("Некит", PAYLOAD)
    assert db.save_draft(d) is True
    assert db.save_draft(d) is False
    assert len(db.all_expenses()) == 1
    assert db.queue_counts("water")["Некит"] == 1


def test_cancelled_cannot_be_saved(tmp_path):
    db = mk(tmp_path)
    d = db.create_draft("Некит", PAYLOAD)
    assert db.cancel_draft(d) is True
    assert db.save_draft(d) is False
    assert db.all_expenses() == []


def test_undo_removes_money_and_turns(tmp_path):
    db = mk(tmp_path)
    d = db.create_draft("Некит", PAYLOAD)
    db.save_draft(d)
    assert db.last_saved_draft("Некит") == d
    assert db.undo_draft(d) is True
    assert db.all_expenses() == []
    assert db.queue_counts("water")["Некит"] == 0
    assert db.last_saved_draft("Некит") is None


def test_mark_paid_once_and_only_parties(tmp_path):
    db = mk(tmp_path)
    i = db.create_pay_item(Transfer("Антон", "Некит", 40000))
    assert db.mark_paid(i, "Полина") is None
    assert db.mark_paid(i, "Антон") == Transfer("Антон", "Некит", 40000)
    assert db.mark_paid(i, "Антон") is None
    assert len(db.all_paid()) == 1
