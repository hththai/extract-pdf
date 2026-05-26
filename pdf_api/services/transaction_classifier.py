import asyncio
from typing import AsyncGenerator
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
