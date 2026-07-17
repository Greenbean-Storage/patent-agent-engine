from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Response:
    status_code: int
    body: Any  # dict | list | str
    duration_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300


class SimulatorClient:
    def __init__(self, base_url: str, timeout: float = 90.0) -> None:
        self.base_url = base_url
        self._http = httpx.Client(base_url=base_url, timeout=timeout)

    def get(self, path: str, **kwargs: Any) -> Response:
        return self._call("GET", path, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Response:
        return self._call("POST", path, json=json, **kwargs)

    def put(self, path: str, json: Any = None, **kwargs: Any) -> Response:
        return self._call("PUT", path, json=json, **kwargs)

    def patch(self, path: str, json: Any = None, **kwargs: Any) -> Response:
        return self._call("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Response:
        return self._call("DELETE", path, **kwargs)

    def request(self, method: str, path: str, **kwargs: Any) -> Response:
        return self._call(method, path, **kwargs)

    def _call(self, method: str, path: str, **kwargs: Any) -> Response:
        t0 = time.monotonic()
        try:
            r = self._http.request(method, path, **kwargs)
            duration = int((time.monotonic() - t0) * 1000)
            try:
                body = r.json()
            except Exception:
                body = r.text
            return Response(status_code=r.status_code, body=body, duration_ms=duration)
        except httpx.ConnectError as exc:
            duration = int((time.monotonic() - t0) * 1000)
            return Response(
                status_code=0,
                body=None,
                duration_ms=duration,
                error=f"connection refused ({exc})",
            )
        except httpx.TimeoutException:
            duration = int((time.monotonic() - t0) * 1000)
            return Response(status_code=0, body=None, duration_ms=duration, error="timeout")
        except Exception as exc:
            duration = int((time.monotonic() - t0) * 1000)
            return Response(status_code=0, body=None, duration_ms=duration, error=str(exc))

    def close(self) -> None:
        self._http.close()
