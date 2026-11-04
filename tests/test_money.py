from splitbot.money import Expense, Transfer, net_balances, settle, fmt_vnd

ALL = ("Некит", "Антон", "Полина")

def test_three_way_split():
    net = net_balances([Expense("Некит", 120_000, ALL)], [])
    assert net == {"Некит": 80_000, "Антон": -40_000, "Полина": -40_000}

def test_pair_split_and_remainder_stays_on_payer():
    net = net_balances([Expense("Антон", 100_001, ("Антон", "Полина"))], [])
    assert net == {"Некит": 0, "Антон": 50_000, "Полина": -50_000}
    net = net_balances([Expense("Некит", 100_000, ALL)], [])
    assert net["Антон"] == -33_333 and net["Некит"] == 66_666

def test_payer_not_in_split():
    net = net_balances([Expense("Некит", 60_000, ("Антон", "Полина"))], [])
    assert net == {"Некит": 60_000, "Антон": -30_000, "Полина": -30_000}

def test_transfers_reduce_debt():
    net = net_balances([Expense("Некит", 120_000, ALL)], [Transfer("Антон", "Некит", 40_000)])
    assert net == {"Некит": 40_000, "Антон": 0, "Полина": -40_000}

def test_mutual_debts_collapse():
    exp = [Expense("Некит", 90_000, ALL), Expense("Антон", 90_000, ALL), Expense("Полина", 30_000, ALL)]
    assert settle(net_balances(exp, [])) == [Transfer("Полина", "Некит", 20_000), Transfer("Полина", "Антон", 20_000)]

def test_settle_even_is_empty():
    assert settle({"Некит": 0, "Антон": 0, "Полина": 0}) == []

def test_fmt():
    assert fmt_vnd(1_234_000) == "1 234 000" and fmt_vnd(500) == "500"
