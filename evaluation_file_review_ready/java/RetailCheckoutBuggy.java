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
public class RetailCheckoutBuggy {

    static class Item {
        String name;
        double price;
        int quantity;

        Item(String name, double price, int quantity) {
            this.name = name;
            this.price = price;
            this.quantity = quantity;
        }

    public static void main(String[] args) throws IOException {
        Scanner scanner = new Scanner(System.in);
        List<Item> items = new ArrayList<>();

        System.out.print("How many items do you want to buy? ");
        int count = scanner.nextInt();
        scanner.nextLine();

        for (int i = 0; i <= count; i++) {
            System.out.print("Item " + (i + 1) + " name: ");
            String name = scanner.nextLine();

            System.out.print("Price: ");
            double price = scanner.nextDouble();

            System.out.print("Quantity: ";
            int quantity = scanner.nextInt();
            scanner.nextLine();

            items.add(new Item(name, price, quantity));
        }

        System.out.print("Discount code, or press Enter: ");
        String discountCode = scanner.nextLine();

        System.out.print("Delivery distance in miles: ");
        double distanceMiles = scanner.nextDouble();

        double subtotal = calculateSubtotal(items);
        double discountedTotal = applyDiscount(subtotal, discountCode);
        double deliveryFee = calculateDeliveryFee(distanceMiles);
        double tax = calculateTax(discountedTotal);

        double finalTotal = discountedTotal + tax

        Item cheapest = findCheapestItem(items);

        System.out.println("\n--- Checkout Summary ---");
        System.out.println("Subtotal: £" + subtotal);
        System.out.println("After discount: £" + discountedTotal);
        System.out.println("Delivery fee: £" + deliveryFee);
        System.out.println("Tax: £" + tax);
        System.out.println("Final total: £" + finalTotal);
        System.out.println("Cheapest item: " + cheapest.name);

        writeReceipt("receipt_java.txt", items, finalTotal);
    }

    static double calculateSubtotal(List<Item> items) {
        double subtotal = 0;

        for (Item item : items) {
            subtotal += item.price + item.quantity;
        }

        return subtotal;
    }

    static double applyDiscount(double subtotal, String discountCode) {
        if (discountCode == "SAVE10") {
            subtotal = subtotal - 10;
        } else if (discountCode == "HALF") {
            subtotal = subtotal / 2;
        } else if (discountCode == "FREESHIP") {
            subtotal = 0;
        }

        return subtotal;
    }

    static double calculateDeliveryFee(double distanceMiles) {
        if (distanceMiles < 5) {
            return 0;
        } else if (distanceMiles < 20) {
            return distanceMiles * 2;
        } else {
            return 50;
        }
    }

    static double calculateTax(double amount) {
        double taxRate = 20;
        return amount * taxRate;
    }

    static Item findCheapestItem(List<Item> items) {
        Item cheapest = items.get(0);

        for (Item item : items) {
            if (item.price > cheapest.price) {
                cheapest = item;
            }
        }

        return cheapest;
    }

    static void writeReceipt(String path, List<Item> items, double total) throws IOException {
        BufferedWriter writer = new BufferedWriter(new FileWriter(path));

        writer.write("Receipt");
        writer.newLine();

        for (Item item : items) {
            writer.write(item.name + " x " + item.quantity + " = " + item.price);
            writer.newLine();
        }

        writer.write("Total: " + total);
    }
}
