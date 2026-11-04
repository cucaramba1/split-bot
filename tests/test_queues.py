from splitbot.queues import equalize_offsets, next_turn

def test_rotation_by_order():
    assert next_turn({"Некит": 0, "Антон": 0, "Полина": 0}) == "Некит"
    assert next_turn({"Некит": 1, "Антон": 0, "Полина": 0}) == "Антон"
    assert next_turn({"Некит": 1, "Антон": 1, "Полина": 0}) == "Полина"

def test_out_of_turn_payment_evens_out():
    c = {"Некит": 1, "Антон": 0, "Полина": 1}   # Полина заплатила вне очереди
    assert next_turn(c) == "Антон"
    c["Антон"] += 1
    assert next_turn(c) == "Некит"

def test_tie_goes_to_longest_idle():
    c = {"Некит": 1, "Антон": 1, "Полина": 1}
    last = {"Некит": 3, "Антон": 1, "Полина": 2}   # Антон ходил раньше всех
    assert next_turn(c, last) == "Антон"
    assert next_turn(c) == "Некит"                    # без истории порядок NAMES


def test_equalize_offsets_lifts_everyone_to_max():
    c = {"Некит": 3, "Антон": 1, "Полина": 2}
    assert equalize_offsets(c) == {"Некит": 0, "Антон": 2, "Полина": 1}
