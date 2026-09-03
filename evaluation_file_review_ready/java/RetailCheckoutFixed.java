import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.Scanner;

/*
 * Retail checkout calculator.
 *
 * Business rules:
 * - Item count must be at least 1.
 * - Each item must have a name.
 * - Price must be 0 or greater.
 * - Quantity must be greater than 0.
 * - Subtotal is price multiplied by quantity for each item.
 * - SAVE10 gives 10% off the item subtotal.
 * - HALF gives 50% off the item subtotal.
 * - FREESHIP removes the delivery fee only.
 * - Delivery is free up to and including 5 miles.
 * - Delivery above 5 and below 20 miles costs 2 pounds per mile after the first 5 miles.
 * - Delivery at 20 miles or above is a fixed 30 pounds.
 * - Tax is 20% of the discounted item subtotal.
 * - Final total is discounted item subtotal plus tax plus delivery.
 */
public class RetailCheckoutFixed {

    static class Item {
        String name;
        double price;
        int quantity;

        Item(String name, double price, int quantity) {
            this.name = name;
            this.price = price;
            this.quantity = quantity;
        }

        double lineTotal() {
            return price * quantity;
        }
    }

    public static void main(String[] args) throws IOException {
        Scanner scanner = new Scanner(System.in);
        List<Item> items = new ArrayList<>();

        int count;
        while (true) {
            System.out.print("How many items do you want to buy? ");
            count = scanner.nextInt();
            scanner.nextLine();

            if (count >= 1) {
                break;
            }
            System.out.println("Please enter at least one item.");
        }

        for (int i = 0; i < count; i++) {
            System.out.print("Item " + (i + 1) + " name: ");
            String name = scanner.nextLine().trim();

            while (name.isEmpty()) {
                System.out.print("Item name cannot be empty. Enter item name: ");
                name = scanner.nextLine().trim();
            }

            double price;
            while (true) {
                System.out.print("Price: ");
                price = scanner.nextDouble();

                if (price >= 0) {
                    break;
                }
                System.out.println("Price cannot be negative.");
            }

            int quantity;
            while (true) {
                System.out.print("Quantity: ");
                quantity = scanner.nextInt();
                scanner.nextLine();

                if (quantity > 0) {
                    break;
                }
                System.out.println("Quantity must be greater than zero.");
            }

            items.add(new Item(name, price, quantity));
        }

        System.out.print("Discount code, or press Enter: ");
        String discountCode = scanner.nextLine();

        double distanceMiles;
        while (true) {
            System.out.print("Delivery distance in miles: ");
            distanceMiles = scanner.nextDouble();

            if (distanceMiles >= 0) {
                break;
            }
            System.out.println("Distance cannot be negative.");
        }

        double subtotal = calculateSubtotal(items);
        double discountedTotal = applyDiscount(subtotal, discountCode);
        double deliveryFee = calculateDeliveryFee(distanceMiles, discountCode);
        double tax = calculateTax(discountedTotal);

        double finalTotal = discountedTotal + tax + deliveryFee;
        Item cheapest = findCheapestItem(items);

        System.out.println("\n--- Checkout Summary ---");
        System.out.printf("Subtotal: £%.2f%n", subtotal);
        System.out.printf("After discount: £%.2f%n", discountedTotal);
        System.out.printf("Delivery fee: £%.2f%n", deliveryFee);
        System.out.printf("Tax: £%.2f%n", tax);
        System.out.printf("Final total: £%.2f%n", finalTotal);
        System.out.println("Cheapest item: " + cheapest.name);

        writeReceipt("receipt_java.txt", items, finalTotal);
        System.out.println("Receipt written to receipt_java.txt");
    }

    static double calculateSubtotal(List<Item> items) {
        double subtotal = 0;

        for (Item item : items) {
            subtotal += item.price * item.quantity;
        }

        return subtotal;
    }

    static double applyDiscount(double subtotal, String discountCode) {
        String code = discountCode == null ? "" : discountCode.trim().toUpperCase();

        if ("SAVE10".equals(code)) {
            subtotal = subtotal * 0.90;
        } else if ("HALF".equals(code)) {
            subtotal = subtotal / 2;
        }

        return Math.max(0, subtotal);
    }

    static double calculateDeliveryFee(double distanceMiles, String discountCode) {
        String code = discountCode == null ? "" : discountCode.trim().toUpperCase();

        if ("FREESHIP".equals(code)) {
            return 0;
        }

        if (distanceMiles <= 5) {
            return 0;
        } else if (distanceMiles < 20) {
            return (distanceMiles - 5) * 2;
        } else {
            return 30;
        }
    }

    static double calculateTax(double amount) {
        double taxRate = 0.20;
        return amount * taxRate;
    }

    static Item findCheapestItem(List<Item> items) {
        Item cheapest = items.get(0);

        for (Item item : items) {
            if (item.price < cheapest.price) {
                cheapest = item;
            }
        }

        return cheapest;
    }

    static void writeReceipt(String path, List<Item> items, double total) throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(path))) {
            writer.write("Receipt");
            writer.newLine();

            for (Item item : items) {
                writer.write(item.name + " x " + item.quantity + " = £" + String.format("%.2f", item.lineTotal()));
                writer.newLine();
            }

            writer.write("Total: £" + String.format("%.2f", total));
        }
    }
}
