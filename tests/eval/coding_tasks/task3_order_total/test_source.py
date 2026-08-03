from source import calculate_subtotal, calculate_tax, calculate_total

def test_subtotal():
    assert calculate_subtotal([{"price": 10, "qty": 2}]) == 20

def test_tax():
    assert calculate_tax(100) == 10

def test_total_no_discount():
    assert calculate_total([{"price": 10, "qty": 2}]) == 22  # 20 * 1.1

def test_total_with_discount():
    # subtotal=20, after_discount=15, tax=1.5, total=16.5
    assert calculate_total([{"price": 10, "qty": 2}], discount=5) == 16.5

def test_total_discount_and_rate():
    # subtotal=50, after_discount=40, tax=40*0.2=8, total=48
    assert calculate_total([{"price": 50, "qty": 1}], tax_rate=0.2, discount=10) == 48
