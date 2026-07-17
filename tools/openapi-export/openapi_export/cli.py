"""OpenAPI 정적 export.

Nexus 게이트웨이가 유일한 외부 REST 표면 (sub-plan ② 코어 컷오버). Nexus 컨테이너의
`GET /api/v1/openapi.json` 을 fetch 해 `.docs/Architectures/external_api/openapi.nexus.json`
으로 저장. DRO 는 외부 표면 0 (control/event/health 내부 전용) — export 대상 아님.

호출:
  uv run --project tools/openapi-export export-openapi
또는:
  make export-openapi
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from venezia_topology import service_url

_OUT_DIR_REL = ".docs/Architectures/external_api"
_TARGETS: list[tuple[str, str]] = [
    # (service_name, output filename suffix) — suffix = DNS 서비스키 (openapi.nexus.json)
    ("nexus", "nexus"),
]


def _output_dir() -> Path:
    # 루트 = 호출 cwd 기준. Makefile 이 cwd=root 보장.
    return Path(os.environ.get("OPENAPI_EXPORT_OUT") or _OUT_DIR_REL)


def _fetch(client: httpx.Client, base: str) -> dict[str, Any]:
    # DRO/Nexus 모두 FastAPI() 에 openapi_url="/api/v1/openapi.json" 설정 (외부 표면 prefix 일치).
    url = f"{base.rstrip('/')}/api/v1/openapi.json"
    r = client.get(url, timeout=10.0)
    r.raise_for_status()
    return r.json()


def main() -> int:
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with httpx.Client() as client:
        for svc, suffix in _TARGETS:
            try:
                base = service_url(svc)
                spec = _fetch(client, base)
            except KeyError:
                errors.append(f"topology.yaml 에 service '{svc}' 정의 없음")
                continue
            except httpx.HTTPError as exc:
                errors.append(f"{svc} ({base}) fetch 실패: {exc}")
                continue
            out_path = out_dir / f"openapi.{suffix}.json"
            out_path.write_text(
                json.dumps(spec, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            print(f"[ok] {svc:8s} → {out_path}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"[err] {e}", file=sys.stderr)
        return 1
    return 0
