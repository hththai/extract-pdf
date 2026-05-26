import asyncio
import json
from typing import AsyncGenerator, Callable
import httpx
import pandas as pd
from config import settings


DEFAULT_DETAIL_COLUMN = "Transaction details"


class TransactionClassifierService:

    def __init__(self):
        self._base_url = settings.AI_BASE_URL.rstrip("/")
        self._model = settings.AI_MODEL
        self._timeout = settings.AI_REQUEST_TIMEOUT
        self._concurrency = settings.AI_CLASSIFY_CONCURRENCY
        self._categories = [c.strip() for c in settings.AI_CLASSIFY_CATEGORIES.split(",")]
        self._system_prompt = settings.AI_CLASSIFY_SYSTEM_PROMPT or self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        cats = "\n".join(f"- {c}" for c in self._categories)
        return (
            "You are a financial transaction classifier. "
            "Given a transaction description, respond with exactly one category from the list below. "
            "Do not explain. Respond only with the category name.\n\n"
            f"Categories:\n{cats}"
        )

    async def classify_from_csv(
        self,
        file_path: str,
        detail_column: str = DEFAULT_DETAIL_COLUMN,
    ) -> pd.DataFrame:
        df = pd.read_csv(file_path)
        return await self.classify_from_dataframe(df, detail_column)

    async def classify_from_dataframe(
        self,
        df: pd.DataFrame,
        detail_column: str = DEFAULT_DETAIL_COLUMN,
    ) -> pd.DataFrame:
        if detail_column not in df.columns:
            raise ValueError(f"Column '{detail_column}' not found in DataFrame")

        df = df.copy()
        semaphore = asyncio.Semaphore(self._concurrency)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async def classify_with_limit(detail: str) -> str:
                async with semaphore:
                    return await self._classify_detail(client, detail)

            categories = await asyncio.gather(
                *[classify_with_limit(str(detail)) for detail in df[detail_column]]
            )

        df["Category"] = list(categories)
        return df

    async def classify_stream(
        self,
        df: pd.DataFrame,
        detail_column: str = DEFAULT_DETAIL_COLUMN,
    ) -> AsyncGenerator[tuple[list, str], None]:
        """Yield (row_values, category) per row, streaming results in order.

        All tasks are submitted immediately; a semaphore limits how many
        Ollama requests run at once. Rows are yielded as soon as each task
        completes, keeping the HTTP connection alive without batch-stall delays.
        """
        if detail_column not in df.columns:
            raise ValueError(f"Column '{detail_column}' not found in DataFrame")

        semaphore = asyncio.Semaphore(self._concurrency)

        async def bounded(detail: str) -> str:
            async with semaphore:
                return await self._classify_detail(client, detail)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            tasks = [
                asyncio.create_task(bounded(str(row[detail_column])))
                for _, row in df.iterrows()
            ]

            for (_, row), task in zip(df.iterrows(), tasks):
                category = await task
                yield list(row), category

    async def _classify_detail(self, client: httpx.AsyncClient, detail: str) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": detail},
            ],
            "stream": False,
        }
        try:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception:
            return "Unknown"


class BatchTransactionClassifierService:
    """Classifies all rows in a few LLM calls (one per chunk of CHUNK_SIZE rows).

    Strategy for accuracy:
    - Chunk into groups of 20 to avoid the "lost in the middle" problem
    - Use Ollama structured JSON output to get a reliable array back
    - Normalize responses against known category names (fuzzy match)
    - Fall back to individual per-row calls for any chunk that returns
      an unexpected response shape
    """

    CHUNK_SIZE = 20

    def __init__(self):
        self._base_url = settings.AI_BASE_URL.rstrip("/")
        self._model = settings.AI_MODEL
        self._timeout = httpx.Timeout(120.0)  # batch calls take longer
        self._categories = [c.strip() for c in settings.AI_CLASSIFY_CATEGORIES.split(",")]
        self._batch_prompt = self._build_batch_prompt()
        self._single_prompt = self._build_single_prompt()

    def _build_batch_prompt(self) -> str:
        cats = "\n".join(f"- {c}" for c in self._categories)
        example = json.dumps(self._categories[:3])
        return (
            "You are a financial transaction classifier.\n"
            "Classify each transaction description into exactly one of these categories:\n\n"
            f"{cats}\n\n"
            "Input: a numbered list of transaction descriptions.\n"
            f"Output: a JSON array of category strings in the same order as the input. "
            f"Example for 3 items: {example}\n"
            "Rules:\n"
            "- Use only the exact category names listed above\n"
            "- Return exactly as many items as the input list\n"
            "- No explanations, no extra keys, only the JSON array"
        )

    def _build_single_prompt(self) -> str:
        cats = "\n".join(f"- {c}" for c in self._categories)
        return (
            "You are a financial transaction classifier. "
            "Given a transaction description, respond with exactly one category from the list below. "
            "Do not explain. Respond only with the category name.\n\n"
            f"Categories:\n{cats}"
        )

    async def classify_dataframe(
        self,
        df: pd.DataFrame,
        detail_column: str = DEFAULT_DETAIL_COLUMN,
        on_progress: Callable[[int], None] | None = None,
    ) -> pd.DataFrame:
        if detail_column not in df.columns:
            raise ValueError(f"Column '{detail_column}' not found in DataFrame")

        details = [str(v) for v in df[detail_column]]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            categories = await self._classify_all(client, details, on_progress)

        result = df.copy()
        result["Category"] = categories
        return result

    async def _classify_all(
        self,
        client: httpx.AsyncClient,
        details: list[str],
        on_progress: Callable[[int], None] | None,
    ) -> list[str]:
        all_categories: list[str] = []
        for start in range(0, len(details), self.CHUNK_SIZE):
            chunk = details[start : start + self.CHUNK_SIZE]
            chunk_cats = await self._classify_chunk(client, chunk)
            all_categories.extend(chunk_cats)
            if on_progress:
                on_progress(len(all_categories))
        return all_categories

    async def _classify_chunk(
        self,
        client: httpx.AsyncClient,
        details: list[str],
    ) -> list[str]:
        numbered = "\n".join(f"{i + 1}. {d}" for i, d in enumerate(details))
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._batch_prompt},
                {"role": "user", "content": numbered},
            ],
            "stream": False,
            "format": "json",
        }
        try:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            parsed = json.loads(resp.json()["message"]["content"])

            # Unwrap if model returned {"categories": [...]} or similar dict
            if isinstance(parsed, dict):
                for v in parsed.values():
                    if isinstance(v, list):
                        parsed = v
                        break

            if isinstance(parsed, list) and len(parsed) == len(details):
                return [self._normalize(str(c)) for c in parsed]
        except Exception:
            pass

        # Chunk response was unusable — fall back to individual calls
        return await self._classify_individually(client, details)

    async def _classify_individually(
        self,
        client: httpx.AsyncClient,
        details: list[str],
    ) -> list[str]:
        semaphore = asyncio.Semaphore(10)

        async def one(detail: str) -> str:
            async with semaphore:
                payload = {
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": self._single_prompt},
                        {"role": "user", "content": detail},
                    ],
                    "stream": False,
                }
                try:
                    resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    return self._normalize(resp.json()["message"]["content"].strip())
                except Exception:
                    return "Unknown"

        return list(await asyncio.gather(*[one(d) for d in details]))

    def _normalize(self, value: str) -> str:
        """Map LLM output back to a known category name."""
        for cat in self._categories:
            if cat.lower() == value.lower():
                return cat
        val_lower = value.lower()
        for cat in self._categories:
            if cat.lower() in val_lower or val_lower in cat.lower():
                return cat
        return "Unknown"
