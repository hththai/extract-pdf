import asyncio
import time
import tracemalloc
from pathlib import Path
from services.transaction_classifier import TransactionClassifierService


def test_classify_transactions_from_csv():
    # Arrange
    csv_path = Path(__file__).parent / "temp" / "true_validation_573.csv"
    output_path = csv_path.with_stem(csv_path.stem + "_classified")
    service = TransactionClassifierService()

    # Act
    tracemalloc.start()
    start_time = time.perf_counter()

    result = asyncio.run(service.classify_from_csv(str(csv_path)))

    elapsed = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result.to_csv(output_path, index=False)

    # Print performance
    print("\n--- Performance ---")
    print(f"  Time elapsed : {elapsed:.2f}s")
    print(f"  Avg per row  : {elapsed / len(result) * 1000:.1f}ms")
    print(f"  Memory (cur) : {current_mem / 1024:.1f} KB")
    print(f"  Memory (peak): {peak_mem / 1024:.1f} KB")

    # Print results
    print(f"\n--- Classified {len(result)} transactions ---")
    print(result[["Transaction details", "Category"]].to_string())
    print(f"\nSaved to: {output_path}")

    # Assert
    assert "Category" in result.columns
    assert len(result) == 573
