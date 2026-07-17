"""probe dialogs — 페르소나별 누적 dialog dump (P-A v3 layout).

DIALOG_NAMES allowlist (`shared/venezia_memory/scaffolding.yaml`) 따라
`runtime/{persona}/dialog/{name}` 자료를 페르소나별로 dump.

옛 P-A v1 의 `probe contexts` (단일 contexts/ namespace) 대체.
"""

from __future__ import annotations

import json

import httpx

from .._common import CM_URL

# venezia_memory.DIALOG_NAMES 와 일치 — 직접 적는 대신 import 가능하면 좋지만
# probe 는 shared/venezia_memory 의존성을 안 들임. allowlist 변동 시 수동 sync.
_DIALOGS_BY_PERSONA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("02.director", ("analysis", "decisions", "evaluation", "workspace")),
    ("03.finder", ("rejection-cases", "research")),
    ("06.inspector", ("evaluation",)),
)


async def run_dialogs(
    user_id: str,
    work_id: str,
    cm_url: str = CM_URL,
) -> int:
    async with httpx.AsyncClient(timeout=10) as http:
        print(f"User:      {user_id}")
        print(f"Invention: {work_id}")
        print()
        for pdir, names in _DIALOGS_BY_PERSONA:
            print(f"[{pdir}]")
            for name in names:
                url = f"{cm_url}/sessions/{user_id}/{work_id}/runtime/{pdir}/dialog/{name}"
                try:
                    r = await http.get(url)
                except Exception as e:  # noqa: BLE001
                    print(f"  ✗ {name:<18}  error: {e}")
                    continue
                if r.status_code == 404:
                    print(f"  ─ {name:<18}  (none)")
                    continue
                if r.status_code != 200:
                    print(f"  ✗ {name:<18}  status={r.status_code}")
                    continue
                data = r.json() if r.text.strip() else {}
                size = len(json.dumps(data, ensure_ascii=False))
                print(f"  ✓ {name:<18}  {size:>6} chars")
        # conversation 은 별도 namespace (00.dro)
        print("[00.dro]")
        url = f"{cm_url}/sessions/{user_id}/{work_id}/runtime/00.dro/conversation"
        r = await http.get(url)
        if r.status_code == 200:
            data = r.json()
            print(f"  ✓ conversation       {len(json.dumps(data, ensure_ascii=False)):>6} chars")
        elif r.status_code == 404:
            print("  ─ conversation       (none)")
        else:
            print(f"  ✗ conversation       status={r.status_code}")
        return 0
