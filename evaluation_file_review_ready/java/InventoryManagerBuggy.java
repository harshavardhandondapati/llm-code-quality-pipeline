import java.util.ArrayList;
import java.util.List;

/*
 * Inventory Manager - intentionally buggy version.
 *
 * Business rules:
 * - Product codes are compared case-insensitively.
 * - Received stock increases quantity.
 * - Dispatch quantity must be > 0 and <= available stock.
 * - Successful dispatch reduces quantity.
 * - Reorder is needed when quantity is below reorder level.
 * - Total inventory value is price * quantity for every product.
 */
public class InventoryManagerBuggy {

    static class Product {
        String code;
        String name;
        double price;
        int quantity;
        int reorderLevel;

        Product(String code, String name, double price, int quantity, int reorderLevel) {
            this.code = code;
            this.name = name;
            this.price = price;
            this.quantity = quantity;
            this.reorderLevel = reorderLevel;
        }
    }

    private final List<Product> products = new ArrayList<>();

    void addProduct(Product product) {
        products.add(product);
    }

    Product findByCode(String code) {
        for (Product product : products) {
            // BUG 1: compares String references instead of values.
            if (product.code == code) {
                return product;
            }
        }
        return null;
    }

    boolean receiveStock(String code, int amount) {
        Product product = findByCode(code);
        if (product == null || amount <= 0) {
            return false;
        }
        product.quantity += amount;
        return true;
    }

    boolean dispatchStock(String code, int amount) {
        Product product = findByCode(code);
        if (product == null || amount <= 0 || amount > product.quantity) {
            return false;
        }

        // BUG 2: dispatch should reduce stock.
        product.quantity += amount;
        return true;
    }

    boolean needsReorder(Product product) {
        // BUG 3: condition is reversed.
        return product.quantity > product.reorderLevel;
    }

    double calculateTotalInventoryValue() {
        double total = 0.0;

        for (Product product : products) {
            // BUG 4: should multiply price by quantity.
            total += product.price + product.quantity;
        }

        return total;
    }

    public static void main(String[] args) {
        InventoryManagerBuggy manager = new InventoryManagerBuggy();

        manager.addProduct(new Product("KB100", "Keyboard", 45.00, 8, 5));
        manager.addProduct(new Product("MS200", "Mouse", 20.00, 3, 4));

        manager.dispatchStock("kb100", 2);

        for (Product product : manager.products) {
            System.out.println(
                product.code + " quantity=" + product.quantity
                + ", reorder=" + manager.needsReorder(product)
            );
        }

        System.out.println(
            "Total inventory value: " + manager.calculateTotalInventoryValue()
        );
    }
}
