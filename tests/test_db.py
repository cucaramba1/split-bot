from splitbot.db import DB
from splitbot.money import Transfer
from splitbot.queues import next_turn

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


def _turn(db, queue, who):
    d = db.create_draft(who, {"payer": who, "items": [], "turns": [{"queue": queue, "who": who}]})
    db.save_draft(d)
    return d


def test_seed_queue_sets_cycle_anton_polina_nekit(tmp_path):
    db = mk(tmp_path)
    for who in ("Некит", "Некит", "Антон"):   # неровная история до настройки
        _turn(db, "water", who)
    db.seed_queue("water", ["Антон", "Полина", "Некит"])
    got = []
    for _ in range(4):
        who = next_turn(db.queue_counts("water"), db.queue_last("water"))
        got.append(who)
        _turn(db, "water", who)
    assert got == ["Антон", "Полина", "Некит", "Антон"]


def test_seed_survives_undo_of_real_turn(tmp_path):
    db = mk(tmp_path)
    db.seed_queue("bike", ["Полина", "Некит", "Антон"])
    d = _turn(db, "bike", "Полина")
    db.undo_draft(d)
    assert next_turn(db.queue_counts("bike"), db.queue_last("bike")) == "Полина"


def test_sync_pay_items_reuses_and_drops_stale(tmp_path):
    from splitbot.money import Transfer
    db = DB(tmp_path / "s.db")
    a = Transfer("Антон", "Некит", 40_000)
    b = Transfer("Полина", "Некит", 40_000)
    first = db.sync_pay_items([a, b])
    again = db.sync_pay_items([a, b])
    assert [i for i, _ in first] == [i for i, _ in again]
    only_a = db.sync_pay_items([a])
    assert [t for _, t in only_a] == [a] and only_a[0][0] == first[0][0]
    assert db.c.execute("SELECT COUNT(*) FROM pay_items").fetchone()[0] == 1
    db.mark_paid(only_a[0][0], "Антон")
    # оплаченное не трогаем
    db.sync_pay_items([])
    assert db.c.execute("SELECT COUNT(*) FROM pay_items").fetchone()[0] == 1
