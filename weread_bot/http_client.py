import asyncio
import time
from typing import Tuple, Any, Dict, List
import httpx


class RateLimiter:
    def __init__(self, rate_limit: int):
        self.rate_limit = max(0, rate_limit)
        self._interval = (60.0 / self.rate_limit) if self.rate_limit > 0 else 0
        self._lock = asyncio.Lock()
        self._last_acquire = 0.0

    async def acquire(self):
        if self.rate_limit <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait_time = self._interval - (now - self._last_acquire)
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = time.monotonic()
            self._last_acquire = now


class HttpClient:
    def __init__(self, timeout: int = 30, retry_times: int = 3, rate_limit: int = 10):
        self.config = type("cfg", (), {"timeout": timeout, "retry_times": retry_times, "retry_delay": "5-15", "rate_limit": rate_limit})
        self.request_times: List[float] = []
        self._rate_limiter = RateLimiter(rate_limit)
        self._client = httpx.AsyncClient(timeout=timeout, limits=httpx.Limits(max_connections=20, max_keepalive_connections=20))

    async def close(self):
        await self._client.aclose()

    async def post_json(self, url: str, data: dict, headers: dict, cookies: dict) -> Tuple[dict, float]:
        response, elapsed = await self._request_with_retries(url, headers=headers, cookies=cookies, json_data=data)
        return response.json(), elapsed

    async def post_raw(self, url: str, headers: dict = None, cookies: dict = None, json_data: dict = None, data: Any = None) -> Tuple[httpx.Response, float]:
        return await self._request_with_retries(url, headers=headers, cookies=cookies, json_data=json_data, data=data)

    async def _request_with_retries(self, url: str, headers: dict = None, cookies: dict = None, json_data: dict = None, data: Any = None) -> Tuple[Any, float]:
        attempts = max(1, self.config.retry_times)
        last_error = None

        for attempt in range(attempts):
            start_time = time.time()
            try:
                await self._rate_limiter.acquire()
                response = await self._client.post(url, headers=headers, cookies=cookies, json=json_data, data=data)
                response.raise_for_status()
                elapsed = time.time() - start_time
                self.request_times.append(elapsed)
                return response, elapsed
            except Exception as exc:
                elapsed = time.time() - start_time
                self.request_times.append(elapsed)
                last_error = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(1)
                else:
                    break

        raise last_error if last_error else RuntimeError("请求失败")

    def get_average_response_time(self) -> float:
        if self.request_times:
            return sum(self.request_times) / len(self.request_times)
        return 0.0
