# File Review Evaluation Cases

These files are evaluation fixtures for the dissertation's File Review workflow.

## Important evaluation rule

Only the files ending in `buggy` / `Buggy` are supplied to the LLM during File Review.
The corresponding `fixed` / `Fixed` files are reference implementations retained only
for evaluation, comparison, and reproducibility. They are not supplied to the LLM.

## Python

### Retail Checkout
- `python/retail_checkout_buggy.py`
- `python/retail_checkout_fixed.py`

This case intentionally contains syntax/runtime and business-logic defects.

### Student Results Analyzer
- `python/student_results_analyzer_buggy.py`
- `python/student_results_analyzer_fixed.py`

This case is syntactically valid and focuses on logical/business-rule defects.

Run:
```bash
python python/student_results_analyzer_buggy.py
python python/student_results_analyzer_fixed.py
```

## Java

### Retail Checkout
- `java/RetailCheckoutBuggy.java`
- `java/RetailCheckoutFixed.java`

The buggy Retail Checkout case intentionally contains compilation and logic defects.
The fixed version can be compiled with:

```bash
javac java/RetailCheckoutFixed.java
java -cp java RetailCheckoutFixed
```

### Inventory Manager
- `java/InventoryManagerBuggy.java`
- `java/InventoryManagerFixed.java`

Both Inventory Manager files compile; the buggy version contains logical defects.

Run:
```bash
javac java/InventoryManagerBuggy.java
java -cp java InventoryManagerBuggy

javac java/InventoryManagerFixed.java
java -cp java InventoryManagerFixed
```
