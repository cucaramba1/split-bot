from splitbot.queues import next_turn, offsets_for_next

def add(a, b): return {k: a[k] + b.get(k, 0) for k in a}

def test_rotation_by_order():
    assert next_turn({"Некит": 0, "Антон": 0, "Полина": 0}) == "Некит"
    assert next_turn({"Некит": 1, "Антон": 0, "Полина": 0}) == "Антон"
    assert next_turn({"Некит": 1, "Антон": 1, "Полина": 0}) == "Полина"

def test_out_of_turn_payment_evens_out():
    c = {"Некит": 1, "Антон": 0, "Полина": 1}   # Полина заплатила вне очереди
    assert next_turn(c) == "Антон"
    c["Антон"] += 1
    assert next_turn(c) == "Некит"

def test_queue_set_start_point():
    c = {"Некит": 3, "Антон": 1, "Полина": 2}
    eff = add(c, offsets_for_next(c, "Полина"))
    assert next_turn(eff) == "Полина"
    eff["Полина"] += 1
    assert next_turn(eff) == "Некит"
    eff["Некит"] += 1
    assert next_turn(eff) == "Антон"
