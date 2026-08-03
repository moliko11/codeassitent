def calculate_subtotal(items):
    """items: [{"price":..., "qty":...}], 返回小计。"""
    return sum(item["price"] * item["qty"] for item in items)


def calculate_tax(amount, rate=0.1):
    """计算税额,默认税率 10%。"""
    return amount * rate


def calculate_total(items, tax_rate=0.1, discount=0):
    """计算订单总价 = (小计 - 折扣) 再加税;税基于折扣后金额。"""
    subtotal = calculate_subtotal(items)
    after_discount = subtotal - discount
    tax = calculate_tax(subtotal, tax_rate)
    return after_discount + tax
