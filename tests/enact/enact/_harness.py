"""enact harness — DRO 역할 대행: RT 합성 · CM seed · Actor dispatch(SSE) · cleanup.

미러 원본 (drift 가드 = reasoning_task 계약 validate + 실 Actor done):
  - step id/system_prompt 부여  = 200.DRO/src/pipeline_walker.py:_convert_single_step
  - RT.input 합성               = 200.DRO/src/orchestrator.py:_build_rt_input
  - output_contract 로드        = 200.DRO/src/orchestrator.py:_load_output_contract (호스트판)
  - SSE 파싱                    = 200.DRO/src/dispatcher.py:parse_sse

queue push / in_flight PATCH 는 의도적으로 안 함 — Actor 는 큐를 읽지 않고
dispatch body 의 rt_id 로 RT 를 직접 GET 한다 (state 검사 없음).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import httpx
import yaml
from probe._common import CM_URL, OPEN_USER_ID
from venezia_contracts import ContractLoader
from venezia_memory import persona_dir
from venezia_pipeline_runtime import load_pipeline_cascaded
from venezia_topology import service_url


def _find_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "@pipelines").is_dir():
            return parent
    raise FileNotFoundError("repo root (@pipelines 보유) 를 찾을 수 없음")


ROOT = _find_root()
PIPELINES_ROOT = ROOT / "@pipelines"
CONTRACTS_ROOT = ROOT / "@contracts"
ACTOR_URL = os.environ.get("ACTOR_URL", service_url("actor"))

_contract_loader = ContractLoader()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def log(msg: str) -> None:
    print(f"[enact] {msg}", flush=True)


def _die(msg: str) -> NoReturn:
    """사용법/환경/입력 오류 = exit 2 (규약 — 검증 FAIL 의 1 과 구분)."""
    print(f"[enact] {msg}", flush=True)
    raise SystemExit(2)


# ─────────────────────────────────────────────────────────────────────────────
# pipeline resolve + RT 합성 (실 pipeline — A3)
# ─────────────────────────────────────────────────────────────────────────────


def resolve_pipeline_id(token: str) -> str:
    """`P01.R00` prefix 또는 full id → full pipeline_id (0건/모호 = fail-loud)."""
    matches = sorted(
        p.name.removesuffix(".pipeline.json")
        for p in PIPELINES_ROOT.rglob(f"{token}*.pipeline.json")
    )
    exact = [m for m in matches if m == token]
    if exact:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        _die(f"pipeline 미발견: {token!r} (@pipelines/**/{token}*.pipeline.json)")
    _die(f"pipeline 모호: {token!r} → {matches}")


def load_steps(pipeline_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """cascading 산출 + walker 동형 coercion (id 보존/순번 문자열, LLM step 에 system_prompt 주입).

    정적 병렬 묶음(nested list, D-6)은 **평탄화** — 각 sub 는 명시 id 를 보유(loader 가 보존)하므로
    독립 flat step 으로 펼친다. enact 는 단일 RT 격리 트랙이라 병렬 묶음도 RT 단위는 동일 — sub 한
    개를 `make enact P02.R00 2`(id 직접) 처럼 골라 단건 합성 가능. is_last/dispatch 는 평탄 list 기준.
    """
    cascaded = load_pipeline_cascaded(pipeline_id, root=PIPELINES_ROOT)
    persona_prompt = cascaded.get("persona_prompt") or ""
    steps: list[dict[str, Any]] = []
    for idx, step in enumerate(cascaded.get("steps") or []):
        group = step if isinstance(step, list) else [step]
        for sub in group:
            merged = dict(sub)
            merged.setdefault("id", str(idx))  # 병렬 sub 는 명시 id 보유 → setdefault 가 honor
            if merged.get("instructions"):
                merged["system_prompt"] = persona_prompt  # composer 가 사용 (walker 동형)
            steps.append(merged)
    return cascaded, steps


def load_output_contract(contract_id: str | None, persona: int | None) -> dict[str, Any] | None:
    """orchestrator._load_output_contract 호스트판 — repo @contracts/{NN}.*/stages/."""
    if not contract_id or persona is None:
        return None
    prefix = f"{persona:02d}."
    for child in CONTRACTS_ROOT.iterdir():
        if child.is_dir() and child.name.startswith(prefix):
            schema_file = child / "stages" / f"{contract_id}.schema.json"
            if schema_file.exists():
                return json.loads(schema_file.read_text(encoding="utf-8"))
    return None


def _build_rt_input(step: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """orchestrator._build_rt_input 동형 (P{NN} 전용 — composer 키 합성)."""
    persona = context.get("__persona__")
    output_contract_id = step.get("output_contract")
    response_schema = (
        load_output_contract(output_contract_id, persona) if output_contract_id else None
    )

    dispatch_to_meta = context.get("__pipeline_dispatch_to__")
    dispatch_choice_guide: dict[int, str] | None = None
    if dispatch_to_meta and context.get("__is_last_step__"):
        actions = dispatch_to_meta.get("actions") or []
        if len(actions) > 1:
            dispatch_choice_guide = {}
            for idx, action_list in enumerate(actions):
                if not isinstance(action_list, list):
                    continue
                if len(action_list) == 0:
                    dispatch_choice_guide[idx] = "(exit — chain 종료)"
                else:
                    dispatch_choice_guide[idx] = "다음 파이프라인: " + ", ".join(action_list)

    return {
        "prompt": "",
        "system_prompt": "",
        "persona_prompt": step.get("system_prompt") or "",
        "inject_context_spec": step.get("effective_inject_context") or {},
        "recommended_context_spec": step.get("effective_recommended_context") or {},
        "fragments": step.get("effective_fragments") or {},
        "instructions": step.get("instructions") or None,
        "dispatch_choice_guide": dispatch_choice_guide,
        "context": {
            "inputs": context.get("inputs", {}),
            "parent_outputs": context.get("parent_outputs", {}),
        },
        "available_tools": step.get("effective_llm_tools") or [],
        "media_refs": step.get("media_refs", []),
        "response_schema": response_schema,
        "step_definition": {
            "id": str(step.get("id", "")),
            "output_contract": output_contract_id,
        },
    }


def _make_rt(
    *,
    pipeline_id: str,
    persona: int,
    chain_id: str,
    step_id: str,
    rt_input: dict[str, Any],
) -> dict[str, Any]:
    rt = {
        "rt_id": str(uuid.uuid4()),
        "chain_id": chain_id,
        "persona": persona,
        "pipeline_id": pipeline_id,
        "step_id": step_id,
        "step_type": "llm_task",
        "input": rt_input,
        "state": "pending",
        "retry_count": 0,
        "max_retries": 3,
        "created_at": now_iso(),
    }
    _contract_loader.assert_valid("reasoning_task", rt)  # drift 가드
    return rt


def select_step(steps: list[dict[str, Any]], token: str | None) -> dict[str, Any]:
    """step 선택 — 숫자(순번=step_id) 또는 id. 생략/범위 밖/tool step = fail-loud + 목록."""

    def _listing() -> str:
        lines = []
        for s in steps:
            kind = "LLM" if s.get("instructions") else f"tool:{s.get('tool')}"
            lines.append(f"  {s['id']}: {kind}  contract={s.get('output_contract')}")
        return "\n".join(lines)

    if token is None:
        _die(f"step 인자 필요 — 사용 가능 step:\n{_listing()}")
    matched = [s for s in steps if s["id"] == token]
    if not matched:
        _die(f"step {token!r} 없음 — 사용 가능 step:\n{_listing()}")
    step = matched[0]
    if not step.get("instructions"):
        _die(
            f"step {token!r} 은 tool step ({step.get('tool')}) — "
            "dispatch 대상 아님 — tool step 은 tool 시나리오(POST /tool)로 검증"
        )
    return step


def synthesize_rt(
    pipeline_token: str,
    step_token: str | None,
    *,
    chain_id: str,
    inputs: dict[str, Any] | None = None,
    drop_composer_keys: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """실 pipeline 합성 (A3) → (RT, step, full pipeline_id).

    drop_composer_keys=True: persona_prompt·inject_context_spec 제거 (errors-c —
    dispatcher 의 composer 키 결손 fail-loud 유도). reasoning_task 계약은 input.required=
    ["prompt"] 만이라 둘을 빼도 통과.
    """
    pipeline_id = resolve_pipeline_id(pipeline_token)
    cascaded, steps = load_steps(pipeline_id)
    step = select_step(steps, step_token)
    is_last = steps and step["id"] == steps[-1]["id"]
    context = {
        "__persona__": cascaded.get("persona"),
        "__pipeline_dispatch_to__": cascaded.get("dispatch_to"),
        "__is_last_step__": bool(is_last),
        "inputs": inputs or {},
        "parent_outputs": {},
    }
    rt_input = _build_rt_input(step, context)
    if drop_composer_keys:
        rt_input.pop("persona_prompt", None)
        rt_input.pop("inject_context_spec", None)
    rt = _make_rt(
        pipeline_id=pipeline_id,
        persona=int(cascaded["persona"]),
        chain_id=chain_id,
        step_id=str(step["id"]),
        rt_input=rt_input,
    )
    return rt, step, pipeline_id


# ─────────────────────────────────────────────────────────────────────────────
# ad-hoc 합성 (B4 — persona + 프롬프트 차터 직접 입력)
# ─────────────────────────────────────────────────────────────────────────────

_SPEC_KEYS = {
    "persona",
    "prompt",
    "instructions",
    "persona_prompt",
    "inject_context",
    "fragments",
    "llm_tools",
    "context",
    "response_schema",
    "output_contract",
    "pipeline_id",
    "step_id",
}


def load_spec(path: str) -> dict[str, Any]:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        _die(f"spec 이 mapping 이 아님: {path}")
    unknown = set(spec) - _SPEC_KEYS
    if unknown:
        _die(f"spec 미지 필드 {sorted(unknown)} — 허용: {sorted(_SPEC_KEYS)}")
    return spec


def synthesize_adhoc_rt(spec: dict[str, Any], *, chain_id: str) -> dict[str, Any]:
    """ad-hoc spec → RT. prompt 는 instructions.inline 설탕 (input.prompt 는 Actor 비소비).

    inject_context 는 cm://·@knowledge/ 만 (composer 계약) — literal 강제 텍스트는 fragments.
    """
    persona = spec.get("persona")
    if not isinstance(persona, int) or not 1 <= persona <= 6:
        _die(f"spec.persona 는 1~6 정수 필수 (got {persona!r})")

    instructions = spec.get("instructions")
    if spec.get("prompt"):
        if instructions:
            _die("spec 의 prompt 와 instructions 는 동시 지정 불가 (XOR)")
        instructions = {"inline": str(spec["prompt"])}
    if not instructions:
        _die("spec 에 prompt 또는 instructions 필수")

    response_schema = spec.get("response_schema")
    if spec.get("output_contract"):
        if response_schema:
            _die("response_schema 와 output_contract 는 동시 지정 불가 (XOR)")
        response_schema = load_output_contract(spec["output_contract"], persona)
        if response_schema is None:
            _die(f"output_contract {spec['output_contract']!r} 로드 실패")

    inject = spec.get("inject_context") or {}
    bad_inject = {
        k: v
        for k, v in inject.items()
        if not (isinstance(v, str) and (v.startswith("cm://") or v.startswith("@knowledge/")))
    }
    if bad_inject:
        _die(
            f"inject_context 는 cm://·@knowledge/ source 만 (composer 계약): {bad_inject} "
            "— literal 강제 텍스트는 fragments 로"
        )

    rt_input = {
        "prompt": "",
        "system_prompt": "",
        "persona_prompt": str(spec.get("persona_prompt") or ""),
        "inject_context_spec": inject,
        "recommended_context_spec": {},
        "fragments": spec.get("fragments") or {},
        "instructions": instructions,
        "dispatch_choice_guide": None,
        "context": {"inputs": (spec.get("context") or {}).get("inputs", {}), "parent_outputs": {}},
        "available_tools": spec.get("llm_tools") or [],
        "media_refs": [],
        "response_schema": response_schema,
        "step_definition": {"id": str(spec.get("step_id", "0")), "output_contract": None},
    }
    return _make_rt(
        pipeline_id=str(spec.get("pipeline_id", "ADHOC")),
        persona=persona,
        chain_id=chain_id,
        step_id=str(spec.get("step_id", "0")),
        rt_input=rt_input,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Actor / CM HTTP (harness = DRO 역할 대행)
# ─────────────────────────────────────────────────────────────────────────────


async def _parse_sse(text_stream: AsyncIterator[str]) -> AsyncIterator[dict[str, Any]]:
    """DRO dispatcher.parse_sse 동형 — event/data 쌍을 dict 로 yield."""
    event: str | None = None
    data_lines: list[str] = []
    async for raw in text_stream:
        line = raw.rstrip("\n")
        if not line:
            if event or data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    data = {"raw": payload}
                yield {"type": event or "message", "data": data}
                event = None
                data_lines = []
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())


@dataclass
class DispatchOutcome:
    status_code: int
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    busy: bool = False
    retry_after: str | None = None


@dataclass
class ToolOutcome:
    status_code: int
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    busy: bool = False
    retry_after: str | None = None


class Harness:
    """Actor·CM 호출 묶음 — 네임스페이스 = (OPEN_USER_ID, work_id) 전용 fresh."""

    def __init__(self, *, timeout_s: float = 120.0) -> None:
        self.user_id = OPEN_USER_ID
        self.timeout_s = timeout_s
        self._http = httpx.AsyncClient(timeout=timeout_s)

    async def close(self) -> None:
        await self._http.aclose()

    # ── Actor ──
    async def actor_health(self) -> dict[str, Any]:
        r = await self._http.get(f"{ACTOR_URL}/health", timeout=10)
        r.raise_for_status()
        return r.json()

    async def dispatch(
        self, work_id: str, persona: int, chain_id: str, rt_id: str
    ) -> DispatchOutcome:
        body = {
            "chain_id": chain_id,
            "rt_id": rt_id,
            "user_id": self.user_id,
            "work_id": work_id,
            "persona": persona,
        }
        async with self._http.stream("POST", f"{ACTOR_URL}/dispatch", json=body) as resp:
            if resp.status_code == 503:
                await resp.aread()
                return DispatchOutcome(
                    status_code=503, busy=True, retry_after=resp.headers.get("Retry-After")
                )
            if resp.status_code >= 400:
                text = (await resp.aread()).decode("utf-8", errors="replace")
                return DispatchOutcome(status_code=resp.status_code, error={"message": text[:300]})
            outcome = DispatchOutcome(status_code=resp.status_code)
            async for evt in _parse_sse(resp.aiter_lines()):
                outcome.events.append(evt)
                if evt["type"] == "result":
                    outcome.result = evt.get("data") or {}
                elif evt["type"] == "error":
                    outcome.error = evt.get("data") or {}
            return outcome

    async def dispatch_concurrent(
        self, work_id: str, persona: int, chain_id: str, rt_ids: list[str]
    ) -> list[DispatchOutcome]:
        """N개 dispatch 동시 진입 — persona cap 포화 결정적 유도 (concurrency 시나리오).

        router 의 release_persona 는 _stream generator 의 finally — client 가 SSE body 를
        읽기 전엔 slot 유지. gather 동시 진입이면 N개 acquire 가 release 보다 먼저 몰려
        cap 초과분이 503. 200 stream 은 본 메서드가 끝까지 소진해 release (cleanup).
        """
        return list(
            await asyncio.gather(*(self.dispatch(work_id, persona, chain_id, r) for r in rt_ids))
        )

    async def tool(self, tool_name: str, params: dict[str, Any]) -> ToolOutcome:
        """POST /tool/{tool_name} 직접 호출 (RT 불요 — pure POST). harness = DRO tool step 대행."""
        r = await self._http.post(f"{ACTOR_URL}/tool/{tool_name}", json={"params": params})
        body: dict[str, Any] = {}
        try:
            body = r.json()
        except (json.JSONDecodeError, ValueError):
            body = {"raw": r.text}
        if r.status_code == 503:
            return ToolOutcome(
                status_code=503, busy=True, result=body, retry_after=r.headers.get("Retry-After")
            )
        if r.status_code >= 400:
            return ToolOutcome(status_code=r.status_code, error=body)
        return ToolOutcome(status_code=r.status_code, result=body)

    # ── CM ──
    def _chain_base(self, work_id: str, persona: int, chain_id: str) -> str:
        pdir = persona_dir(persona)
        return f"{CM_URL}/sessions/{self.user_id}/{work_id}/runtime/{pdir}/{chain_id}"

    async def create_chain(
        self, work_id: str, persona: int, chain_id: str, pipeline_id: str
    ) -> None:
        r = await self._http.post(
            f"{CM_URL}/sessions/{self.user_id}/{work_id}/runtime",
            json={
                "pipeline_id": pipeline_id,
                "persona": persona,
                "chain_id": chain_id,
                "trigger": {"kind": "enact"},
            },
        )
        r.raise_for_status()

    async def create_rt(
        self, work_id: str, persona: int, chain_id: str, rt: dict[str, Any]
    ) -> None:
        r = await self._http.post(f"{self._chain_base(work_id, persona, chain_id)}/rts", json=rt)
        r.raise_for_status()

    async def get_rt(self, work_id: str, persona: int, chain_id: str, rt_id: str) -> dict[str, Any]:
        r = await self._http.get(f"{self._chain_base(work_id, persona, chain_id)}/rts/{rt_id}")
        r.raise_for_status()
        return r.json()

    async def get_agent_state(self, work_id: str, persona: int, chain_id: str) -> dict[str, Any]:
        r = await self._http.get(f"{self._chain_base(work_id, persona, chain_id)}/agent_state")
        r.raise_for_status()
        return r.json()

    async def get_trail(self, work_id: str, persona: int, chain_id: str) -> list[dict[str, Any]]:
        r = await self._http.get(f"{self._chain_base(work_id, persona, chain_id)}/trail")
        r.raise_for_status()
        return [json.loads(line) for line in r.text.splitlines() if line.strip()]

    async def put_raw_agent_state(
        self, work_id: str, persona: int, chain_id: str, state: dict[str, Any]
    ) -> None:
        """CM 에 임의 dict 를 agent_state 로 PUT (errors-d — CM 은 pass-through, 검증 0).

        Actor 가 parse_agent_state 로 읽을 때 평문 messages = fail-loud (legacy 폐기 포맷).
        """
        r = await self._http.put(
            f"{self._chain_base(work_id, persona, chain_id)}/agent_state", json=state
        )
        r.raise_for_status()

    async def cleanup(self, work_id: str) -> None:
        """probe clean 재사용 — prefix 전체 삭제 (PASS 시에만 호출)."""
        from probe.commands.clean import run_clean

        await run_clean(self.user_id, work_id, yes=True, cm_url=CM_URL)


def new_work_id() -> str:
    return f"enact-{uuid.uuid4().hex[:12]}"


def new_chain_id(tag: str) -> str:
    return f"enact-{tag}-{uuid.uuid4().hex[:8]}"
