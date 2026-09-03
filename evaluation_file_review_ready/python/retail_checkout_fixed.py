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

    while True:
        try:
            count = int(input("How many items do you want to buy? "))
            if count < 1:
                print("Please enter at least one item.")
                continue
            break
        except ValueError:
            print("Please enter a valid whole number.")

    for i in range(count):
        name = input(f"Item {i + 1} name: ").strip()
        while not name:
            name = input("Item name cannot be empty. Enter item name: ").strip()

        while True:
            try:
                price = float(input("Price: "))
                if price < 0:
                    print("Price cannot be negative.")
                    continue
                break
            except ValueError:
                print("Please enter a valid price.")

        while True:
            try:
                quantity = int(input("Quantity: "))
                if quantity <= 0:
                    print("Quantity must be greater than zero.")
                    continue
                break
            except ValueError:
                print("Please enter a valid whole number.")

        items.append({"name": name, "price": price, "quantity": quantity})

    return items


def calculate_subtotal(items):
    subtotal = 0.0
    for item in items:
        subtotal += item["price"] * item["quantity"]
    return subtotal


def apply_discount(subtotal, discount_code):
    code = discount_code.strip().upper()

    if code == "SAVE10":
        subtotal = subtotal * 0.90
    elif code == "HALF":
        subtotal = subtotal / 2

    return max(0.0, subtotal)


def calculate_delivery_fee(distance_miles, discount_code=""):
    if distance_miles < 0:
        raise ValueError("Delivery distance cannot be negative.")

    if discount_code.strip().upper() == "FREESHIP":
        return 0.0

    if distance_miles <= 5:
        return 0.0
    if distance_miles < 20:
        return (distance_miles - 5) * 2
    return 30.0


def calculate_tax(amount):
    tax_rate = 0.20
    return amount * tax_rate


def find_cheapest_item(items):
    return min(items, key=lambda item: item["price"])


def write_receipt(file_path, items, total):
    with open(file_path, "w", encoding="utf-8") as receipt:
        receipt.write("Receipt\n")
        for item in items:
            line_total = item["price"] * item["quantity"]
            receipt.write(f"{item['name']} x {item['quantity']} = £{line_total:.2f}\n")
        receipt.write(f"Total: £{total:.2f}\n")


def main():
    print("Retail Checkout Calculator")
    items = read_items()

    discount_code = input("Discount code, or press Enter: ")

    while True:
        try:
            distance_miles = float(input("Delivery distance in miles: "))
            if distance_miles < 0:
                print("Distance cannot be negative.")
                continue
            break
        except ValueError:
            print("Please enter a valid distance.")

    subtotal = calculate_subtotal(items)
    discounted_total = apply_discount(subtotal, discount_code)
    delivery_fee = calculate_delivery_fee(distance_miles, discount_code)
    tax = calculate_tax(discounted_total)

    final_total = discounted_total + tax + delivery_fee
    cheapest = find_cheapest_item(items)

    print("\n--- Checkout Summary ---")
    print(f"Subtotal: £{subtotal:.2f}")
    print(f"After discount: £{discounted_total:.2f}")
    print(f"Delivery fee: £{delivery_fee:.2f}")
    print(f"Tax: £{tax:.2f}")
    print(f"Final total: £{final_total:.2f}")
    print(f"Cheapest item: {cheapest['name']}")

    write_receipt("receipt.txt", items, final_total)
    print("Receipt written to receipt.txt")


if __name__ == "__main__":
    main()
