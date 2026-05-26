import asyncio
import json
import math
import time
import tracemalloc
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from services.transaction_classifier import BatchTransactionClassifierService, TransactionClassifierService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass  # simulates a 2xx response; no exception to raise

    def json(self):
        return {"message": {"content": self._content}}


def _patch_client(responses: list[str]):
    """Patch httpx.AsyncClient so each post() call returns the next response."""
    it = iter(responses)

    def _post(*_args, **_kwargs):
        return _MockResponse(next(it))

    mock = AsyncMock()
    mock.post.side_effect = _post
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


# ---------------------------------------------------------------------------
# TransactionClassifierService — existing integration test
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# BatchTransactionClassifierService — unit tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestNormalize:
    def setup_method(self):
        self.svc = BatchTransactionClassifierService()
        self.cats = self.svc._categories

    def test_exact_match(self):
        assert self.svc._normalize(self.cats[0]) == self.cats[0]

    def test_case_insensitive(self):
        assert self.svc._normalize(self.cats[0].upper()) == self.cats[0]

    def test_partial_match_substring(self):
        # "Food" should resolve to "Food and Dining"
        result = self.svc._normalize("Food")
        assert result in self.cats

    def test_unknown_value_returns_unknown(self):
        assert self.svc._normalize("zzz_no_match_xyz") == "Unknown"

    def test_empty_string_returns_unknown(self):
        assert self.svc._normalize("") == "Unknown"


class TestClassifyChunk:
    def setup_method(self):
        self.svc = BatchTransactionClassifierService()
        self.cats = self.svc._categories

    def test_valid_json_array_response(self):
        details = ["GRAB FOOD", "SHELL PETROL", "NTUC FAIRPRICE"]
        expected = self.cats[:3]
        mock_client = _patch_client([json.dumps(expected)])

        result = asyncio.run(self.svc._classify_chunk(mock_client, details))

        assert result == expected
        assert mock_client.post.call_count == 1

    def test_dict_response_is_unwrapped(self):
        # Model returns {"categories": [...]} instead of bare array
        details = ["TXN A", "TXN B"]
        expected = self.cats[:2]
        mock_client = _patch_client([json.dumps({"categories": expected})])

        result = asyncio.run(self.svc._classify_chunk(mock_client, details))

        assert result == expected

    def test_wrong_count_falls_back_to_individual(self):
        details = ["TXN A", "TXN B", "TXN C"]
        # Batch returns only 2 items → mismatch → 3 individual calls follow
        batch_resp = json.dumps(self.cats[:2])
        individual_resps = [self.cats[i % len(self.cats)] for i in range(3)]
        mock_client = _patch_client([batch_resp] + individual_resps)

        result = asyncio.run(self.svc._classify_chunk(mock_client, details))

        assert len(result) == 3
        assert mock_client.post.call_count == 4  # 1 batch + 3 individual

    def test_invalid_json_falls_back_to_individual(self):
        details = ["TXN A", "TXN B"]
        individual_resps = [self.cats[0], self.cats[1]]
        mock_client = _patch_client(["not valid json"] + individual_resps)

        result = asyncio.run(self.svc._classify_chunk(mock_client, details))

        assert len(result) == 2
        assert mock_client.post.call_count == 3  # 1 failed batch + 2 individual

    def test_normalize_applied_to_responses(self):
        details = ["TXN A"]
        # Model returns category in uppercase — should still resolve
        upper = self.cats[0].upper()
        mock_client = _patch_client([json.dumps([upper])])

        result = asyncio.run(self.svc._classify_chunk(mock_client, details))

        assert result == [self.cats[0]]


class TestClassifyDataframe:
    def setup_method(self):
        self.svc = BatchTransactionClassifierService()
        self.cats = self.svc._categories

    def _make_df(self, n: int) -> pd.DataFrame:
        return pd.DataFrame({"Transaction details": [f"TXN {i}" for i in range(n)]})

    def _chunk_responses(self, n: int) -> list[str]:
        chunks = math.ceil(n / self.svc.CHUNK_SIZE)
        return [
            json.dumps([self.cats[i % len(self.cats)] for i in range(min(self.svc.CHUNK_SIZE, n - c * self.svc.CHUNK_SIZE))])
            for c in range(chunks)
        ]

    def test_category_column_added(self):
        df = self._make_df(5)
        with patch("services.transaction_classifier.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _patch_client(self._chunk_responses(5))
            result = asyncio.run(self.svc.classify_dataframe(df))

        assert "Category" in result.columns
        assert len(result) == 5

    def test_original_df_not_mutated(self):
        df = self._make_df(5)
        original_cols = list(df.columns)
        with patch("services.transaction_classifier.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _patch_client(self._chunk_responses(5))
            asyncio.run(self.svc.classify_dataframe(df))

        assert list(df.columns) == original_cols

    def test_progress_callback_fires_per_chunk(self):
        n = self.svc.CHUNK_SIZE * 2 + 5  # 3 chunks
        df = self._make_df(n)
        progress_log: list[int] = []

        with patch("services.transaction_classifier.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _patch_client(self._chunk_responses(n))
            asyncio.run(self.svc.classify_dataframe(df, on_progress=progress_log.append))

        assert len(progress_log) == 3
        assert progress_log[-1] == n

    def test_missing_column_raises(self):
        df = pd.DataFrame({"Wrong column": ["TXN A"]})
        with pytest.raises(ValueError, match="not found"):
            asyncio.run(self.svc.classify_dataframe(df))

    def test_all_categories_are_known(self):
        n = 10
        df = self._make_df(n)
        with patch("services.transaction_classifier.httpx.AsyncClient") as MockClient:
            MockClient.return_value = _patch_client(self._chunk_responses(n))
            result = asyncio.run(self.svc.classify_dataframe(df))

        valid = set(self.cats) | {"Unknown"}
        assert set(result["Category"]).issubset(valid)


# ---------------------------------------------------------------------------
# BatchTransactionClassifierService — integration test (requires live Ollama)
# ---------------------------------------------------------------------------

def test_batch_classify_transactions_from_csv():
    csv_path = Path(__file__).parent / "temp" / "true_validation_573.csv"
    output_path = csv_path.with_stem(csv_path.stem + "_batch_classified")
    svc = BatchTransactionClassifierService()

    tracemalloc.start()
    start_time = time.perf_counter()

    result = asyncio.run(svc.classify_dataframe(pd.read_csv(csv_path)))

    elapsed = time.perf_counter() - start_time
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    result.to_csv(output_path, index=False)

    print(f"\n--- Batch Performance ({math.ceil(len(result) / svc.CHUNK_SIZE)} chunks of {svc.CHUNK_SIZE}) ---")
    print(f"  Rows        : {len(result)}")
    print(f"  Time elapsed: {elapsed:.2f}s")
    print(f"  Avg per row : {elapsed / len(result) * 1000:.1f}ms")
    print(f"  Memory (cur): {current_mem / 1024:.1f} KB")
    print(f"  Memory (peak): {peak_mem / 1024:.1f} KB")
    print("\n--- Category distribution ---")
    print(result["Category"].value_counts().to_string())
    print(f"\nSaved to: {output_path}")

    assert "Category" in result.columns
    assert len(result) == 573
    assert result["Category"].notna().all()
    assert set(result["Category"]).issubset(set(svc._categories) | {"Unknown"})
