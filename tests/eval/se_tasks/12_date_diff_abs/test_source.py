from datetime import date
from source import days_between
def test_order1():
    assert days_between(date(2026,1,1), date(2026,1,5)) == 4
def test_order2():
    assert days_between(date(2026,1,5), date(2026,1,1)) == 4
def test_same():
    assert days_between(date(2026,1,1), date(2026,1,1)) == 0
