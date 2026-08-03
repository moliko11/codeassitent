def calculate_subtotal(items):
    return sum(item["price"] * item["qty"] for item in items)


def calculate_tax(amount, rate=0.1):
    return amount * rate


def calculate_total(items, tax_rate=0.1, discount=0):
    subtotal = calculate_subtotal(items)
    after_discount = subtotal - discount
    tax = calculate_tax(after_discount, tax_rate)
    return after_discount + tax
