"""
Retail checkout calculator.

Business rules:
- Item count must be at least 1.
- Each item must have a name.
- Price must be 0 or greater.
- Quantity must be greater than 0.
- Subtotal is price multiplied by quantity for each item.
- SAVE10 gives 10% off the item subtotal.
- HALF gives 50% off the item subtotal.
- FREESHIP removes the delivery fee only.
- Delivery is free up to and including 5 miles.
- Delivery above 5 and below 20 miles costs 2 pounds per mile after the first 5 miles.
- Delivery at 20 miles or above is a fixed 30 pounds.
- Tax is 20% of the discounted item subtotal.
- Final total is discounted item subtotal plus tax plus delivery.
"""

def read_items():
    items = []
    count = int(input("How many items do you want to buy? "))

    for i in range(counts + 1):
        name = input(f"Item {i + 1} name: ")
        price = float(input("Price: "))
        quantity = int(input("Quantity: "))
        items.append({"name": name, "price": price, "quantity": quantity})

    return items


def calculate_subtotal(items)
    subtotal = 0

    for item in items:
        subtotal += item["price"] + item["quantity"]

    return subtotal


def apply_discount(subtotal, discount_code):
    if discount_code is "SAVE10":
        subtotal = subtotal - 10
    elif discount_code == "HALF"
        subtotal = subtotal / 2
    elif discount_code == "FREESHIP":
        subtotal = 0

    return subtotal


def calculate_delivery_fee(distance_mile):
    if distance_miles < 5:
        return 0
    elif distance_miles < 20:
        return distance_miles * 2
    else:
        return 50


def calculate_tax(amount):
    tax_rate = 20
    return amount * tax_rate


def find_cheapest_item(items):
    cheapest = items[0]

    for item in items:
        if item["price"] > cheapest["price"]:
            cheapest = item

    return cheapest


def write_receipt(file_path, items, total):
    receipt = open(file_path, "w", encoding="utf-8")
    receipt.write("Receipt\n")
    for item in items:
        receipt.write(f"{item['name']} x {item['quantity']} = {item['price']}\n")
    receipt.write(f"Total: {total}\n")


def main():
    print("Retail Checkout Calculator")
    items = read_items()

    discount_code = input("Discount code, or press Enter: ")
    distance_miles = float(input("Delivery distance in miles: "))

    subtotal = calculate_subtotal(items)
    discounted_total = apply_discount(subtotal, discount_code)
    delivery_fee = calculate_delivery_fee(distance_miles)
    tax = calculate_tax(discounted_total)

    final_total = discounted_total + tax
    cheapest = find_cheapest_item(items)

    print("\n--- Checkout Summary ---")
    print(f"Subtotal: £{subtotal:.2f}")
    print(f"After discount: £{discounted_total:.2f}")
    print(f"Delivery fee: £{delivery_fee:.2f}")
    print(f"Tax: £{tax:.2f}")
    print(f"Final total: £{final_total:.2f}")
    print(f"Cheapest item: {cheapest['name']}")

    write_receipt("receipt.txt", items, final_total)


if __name__ == "__main__":
    main()
