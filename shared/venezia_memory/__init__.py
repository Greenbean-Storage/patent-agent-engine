"""venezia_memory — S3 path/key 의 단일 source. (P-A v3 final)

scaffolding.yaml 을 import 시 1 회 로드. 모든 컴포넌트 (CM/DRO/Actor) 가
이 모듈의 builder 함수를 호출해서 path 생성. 직접 literal 사용 금지.

핵심:
- dialogs/ 카테고리 폐기 → runtime/ 통합
- runtime/00.dro/ = DRO 자체 자료 (conversation)
- runtime/{persona_dir}/ = 페르소나별 (queue.json + 누적 dialog + chain 자료)
- chain_queue 완전 폐기 — RT 큐는 (session,persona) 단일 worker 가 chain-at-a-time 소비
- DIALOG_NAMES = 페르소나별 dict

페르소나 매핑:
    1 = 01.buddy
    2 = 02.director
    3 = 03.finder
    4 = 04.thinker
    5 = 05.crafter
    6 = 06.inspector

00.dro 는 페르소나가 아니지만 sub-folder 이름으로 동일 패턴.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml  # type: ignore[import-untyped]


def _load_scaffolding() -> dict[str, Any]:
    path = Path(__file__).parent / "scaffolding.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_SCAFFOLDING: Final[dict[str, Any]] = _load_scaffolding()

# ── exported constants ───────────────────────────────────────────────────────

SCHEMA_VERSION: Final[str] = _SCAFFOLDING["schema_version"]
ROOT_PREFIX: Final[str] = _SCAFFOLDING["root_prefix"]
ENTITY_PATH: Final[str] = _SCAFFOLDING["entity_path"]
ROOT_MANIFEST: Final[str] = _SCAFFOLDING["root_manifest"]

# users/ — 인증·식별 루트 (sessions 와 별개). PII 0.
_USERS: Final[dict[str, Any]] = _SCAFFOLDING["users"]
USERS_ROOT_PREFIX: Final[str] = _USERS["root_prefix"]
_IDENTITIES_PATH: Final[str] = _USERS["identities"]["path"]
_IDENTITY_FILE: Final[str] = _USERS["identities"]["file"]
_PROFILES_PATH: Final[str] = _USERS["profiles"]["path"]
_PROFILE_FILE: Final[str] = _USERS["profiles"]["files"]["profile"]
_IDEMPOTENCY_PATH: Final[str] = _USERS["idempotency"]["path"]
_IDEMPOTENCY_FILE: Final[str] = _USERS["idempotency"]["file"]
_REFRESH_TOKENS_PATH: Final[str] = _USERS["refresh_tokens"]["path"]
_REFRESH_TOKEN_FILE: Final[str] = _USERS["refresh_tokens"]["file"]

NS_RUNTIME: Final[str] = "runtime"
NS_MODELS: Final[str] = "models"
NS_DRAWINGS: Final[str] = "drawings"
NS_OUTPUTS: Final[str] = "outputs"
NS_MEDIA: Final[str] = "media"

# 페르소나 디렉토리 매핑 (코드 안 persona: int 1~6 → path segment)
PERSONA_DIRS: Final[dict[int, str]] = {
    1: "01.buddy",
    2: "02.director",
    3: "03.finder",
    4: "04.thinker",
    5: "05.crafter",
    6: "06.inspector",
}
DRO_DIR: Final[str] = "00.dro"


def _ns(name: str) -> dict[str, Any]:
    return _SCAFFOLDING["namespaces"][name]


_RUNTIME_NS: Final[dict[str, Any]] = _ns(NS_RUNTIME)
_MODELS_NS: Final[dict[str, Any]] = _ns(NS_MODELS)
_DRAWINGS_NS: Final[dict[str, Any]] = _ns(NS_DRAWINGS)
_OUTPUTS_NS: Final[dict[str, Any]] = _ns(NS_OUTPUTS)
_MEDIA_NS: Final[dict[str, Any]] = _ns(NS_MEDIA)

# manifest filenames
MANIFEST_RUNTIME: Final[str] = _RUNTIME_NS["manifest"]
MANIFEST_MODELS: Final[str] = _MODELS_NS["manifest"]
MANIFEST_OUTPUTS: Final[str] = _OUTPUTS_NS["manifest"]
MANIFEST_DRAWINGS: Final[str] = _DRAWINGS_NS["manifest"]

# resource files
IOM_FILE: Final[str] = _MODELS_NS["files"]["iom"]
CMM_FILE: Final[str] = _MODELS_NS["files"]["cmm"]
USER_ROADMAP_FILE: Final[str] = _MODELS_NS["files"]["user_roadmap"]
CONCEPT_DISCOVERY_STACK_FILE: Final[str] = _MODELS_NS["files"]["concept_discovery_stack"]

# runtime sub-paths (templates)
_RUNTIME_DRO_SUB: Final[dict[str, Any]] = _RUNTIME_NS["sub_dirs"]["dro"]
_RUNTIME_DRO_PATH: Final[str] = _RUNTIME_DRO_SUB["path"]
_DRO_CONVERSATION_FILE: Final[str] = _RUNTIME_DRO_SUB["files"]["conversation"]

_RUNTIME_PERSONA_SUB: Final[dict[str, Any]] = _RUNTIME_NS["sub_dirs"]["persona"]
_PERSONA_QUEUE_FILE: Final[str] = _RUNTIME_PERSONA_SUB["files"]["queue"]
_PERSONA_CHAIN_SUB: Final[dict[str, Any]] = _RUNTIME_PERSONA_SUB["sub_dirs"]["chain"]
_PERSONA_CHAIN_PATH: Final[str] = _PERSONA_CHAIN_SUB["path"]
_PERSONA_CHAIN_MANIFEST: Final[str] = _PERSONA_CHAIN_SUB["files"]["manifest"]
_PERSONA_CHAIN_TRAIL: Final[str] = _PERSONA_CHAIN_SUB["files"]["trail"]
_PERSONA_CHAIN_RT: Final[str] = _PERSONA_CHAIN_SUB["files"]["rt"]
_PERSONA_CHAIN_AGENT_STATE: Final[str] = _PERSONA_CHAIN_SUB["files"]["agent_state"]

# 페르소나별 누적 dialog allowlist (DIALOG_NAMES)
DIALOG_NAMES: Final[dict[str, frozenset[str]]] = {
    k: frozenset(v) for k, v in _RUNTIME_PERSONA_SUB["dialog_allowlist"].items()
}

# outputs/drawings/media
_OUTPUTS_FILE_TEMPLATE: Final[str] = _OUTPUTS_NS["file_template"]
_MEDIA_FILE_TEMPLATE: Final[str] = _MEDIA_NS["file_template"]
_DRAWINGS_SUB: Final[dict[str, Any]] = _DRAWINGS_NS["sub_dirs"]["drawing"]
_DRAWINGS_PATH: Final[str] = _DRAWINGS_SUB["path"]
_DRAWINGS_NUMERALS: Final[str] = _DRAWINGS_SUB["files"]["numerals"]
_DRAWINGS_DL: Final[str] = _DRAWINGS_SUB["files"]["dl"]
_DRAWINGS_FIGURE: Final[str] = _DRAWINGS_SUB["files"]["figure"]


# ── key builders ─────────────────────────────────────────────────────────────


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def persona_dir(persona: int) -> str:
    """1~6 → '01.buddy' / '02.director' / ..."""
    if persona not in PERSONA_DIRS:
        raise ValueError(f"persona must be 1..6, got {persona}")
    return PERSONA_DIRS[persona]


def session_root(user_id: str, work_id: str) -> str:
    """sessions/{user_id}/{work_id}"""
    return ENTITY_PATH.format(user_id=user_id, work_id=work_id)


# ── users/ (인증·식별 — sessions 와 별개 루트, PII 0) ─────────────────────────


def identity_key(provider: str, provider_sub: str) -> str:
    """users/identities/{provider}/{provider_sub}.json = { user_id }.

    로그인 인덱스 — (provider, sub) → 우리 user_id 를 O(1) 조회. writer = Account.
    """
    return _join(
        USERS_ROOT_PREFIX,
        _IDENTITIES_PATH.format(provider=provider),
        _IDENTITY_FILE.format(provider_sub=provider_sub),
    )


def profile_key(user_id: str) -> str:
    """users/profiles/{user_id}/profile.json = { nickname, providers, created_at }. PII 0."""
    return _join(
        USERS_ROOT_PREFIX,
        _PROFILES_PATH.format(user_id=user_id),
        _PROFILE_FILE,
    )


def idempotency_key(user_id: str, key_hash: str) -> str:
    """users/idempotency/{user_id}/{key_hash}.json — Idempotency-Key 영속 record (D6, user-level).

    key_hash = sha256(client Idempotency-Key) hex (파일명·URL 안전). record 형식은 store.py 참조.
    """
    return _join(
        USERS_ROOT_PREFIX,
        _IDEMPOTENCY_PATH.format(user_id=user_id),
        _IDEMPOTENCY_FILE.format(key_hash=key_hash),
    )


def refresh_token_key(user_id: str, family_id: str) -> str:
    """users/refresh-tokens/{user_id}/{family_id}.json — refresh family (C1 인증).

    회전·재사용 탐지·logout revoke 의 서버측 상태. record 형식은 400.CM/src/store.py 참조.
    """
    return _join(
        USERS_ROOT_PREFIX,
        _REFRESH_TOKENS_PATH.format(user_id=user_id),
        _REFRESH_TOKEN_FILE.format(family_id=family_id),
    )


def context_manifest_key(user_id: str, work_id: str) -> str:
    """root manifest. manifest.context.yaml"""
    return _join(session_root(user_id, work_id), ROOT_MANIFEST)


# ── runtime/ ──────────────────────────────────────────────────────────────────


def runtime_root(user_id: str, work_id: str) -> str:
    return _join(session_root(user_id, work_id), NS_RUNTIME)


def runtime_manifest_key(user_id: str, work_id: str) -> str:
    """runtime/manifest.runtime.yaml — 전체 세션 chain 인덱스 (페르소나 무관)."""
    return _join(runtime_root(user_id, work_id), MANIFEST_RUNTIME)


# ── runtime/00.dro/ (DRO 자체 자료) ───────────────────────────────────────────


def dro_root(user_id: str, work_id: str) -> str:
    return _join(runtime_root(user_id, work_id), _RUNTIME_DRO_PATH)


def conversation_key(user_id: str, work_id: str) -> str:
    """사용자-시스템 대화. writer = DRO."""
    return _join(dro_root(user_id, work_id), _DRO_CONVERSATION_FILE)


# ── runtime/{persona}/ (페르소나별: queue + 누적 dialog + chain 자료) ─────────


def persona_root(user_id: str, work_id: str, persona: int) -> str:
    return _join(runtime_root(user_id, work_id), persona_dir(persona))


def queue_key(user_id: str, work_id: str, persona: int) -> str:
    """RT 큐. runtime/{persona}/queue.json"""
    return _join(persona_root(user_id, work_id, persona), _PERSONA_QUEUE_FILE)


def persona_dialog_key(user_id: str, work_id: str, persona: int, name: str) -> str:
    """페르소나별 누적 dialog. runtime/{persona}/{name}.json. allowlist 검증."""
    pdir = persona_dir(persona)
    if name not in DIALOG_NAMES.get(pdir, frozenset()):
        raise ValueError(
            f"unknown dialog name {name!r} for persona {pdir}. "
            f"allowed: {sorted(DIALOG_NAMES.get(pdir, frozenset()))}"
        )
    return _join(persona_root(user_id, work_id, persona), f"{name}.json")


def chain_dir(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return _join(
        persona_root(user_id, work_id, persona),
        _PERSONA_CHAIN_PATH.format(chain_id=chain_id),
    )


def chain_manifest_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return _join(chain_dir(user_id, work_id, persona, chain_id), _PERSONA_CHAIN_MANIFEST)


def trail_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    return _join(chain_dir(user_id, work_id, persona, chain_id), _PERSONA_CHAIN_TRAIL)


def rt_key(user_id: str, work_id: str, persona: int, chain_id: str, rt_id: str) -> str:
    return _join(
        chain_dir(user_id, work_id, persona, chain_id),
        _PERSONA_CHAIN_RT.format(rt_id=rt_id),
    )


def agent_state_key(user_id: str, work_id: str, persona: int, chain_id: str) -> str:
    """chain 안의 agent state. 1 chain 1 파일 (페르소나는 path 로 식별)."""
    return _join(chain_dir(user_id, work_id, persona, chain_id), _PERSONA_CHAIN_AGENT_STATE)


# ── models/ ───────────────────────────────────────────────────────────────────


def models_root(user_id: str, work_id: str) -> str:
    return _join(session_root(user_id, work_id), NS_MODELS)


def models_manifest_key(user_id: str, work_id: str) -> str:
    return _join(models_root(user_id, work_id), MANIFEST_MODELS)


def iom_key(user_id: str, work_id: str) -> str:
    return _join(models_root(user_id, work_id), IOM_FILE)


def cmm_key(user_id: str, work_id: str) -> str:
    return _join(models_root(user_id, work_id), CMM_FILE)


def user_roadmap_key(user_id: str, work_id: str) -> str:
    return _join(models_root(user_id, work_id), USER_ROADMAP_FILE)


def concept_discovery_stack_key(user_id: str, work_id: str) -> str:
    """구체화 단계 정보 stack — 사용자 말 차곡차곡 누적. 모델 아님 (IOM precursor).
    models/concept-discovery-stack.json. writer: P02 director."""
    return _join(models_root(user_id, work_id), CONCEPT_DISCOVERY_STACK_FILE)


# ── outputs/ ──────────────────────────────────────────────────────────────────


def outputs_root(user_id: str, work_id: str) -> str:
    return _join(session_root(user_id, work_id), NS_OUTPUTS)


def outputs_manifest_key(user_id: str, work_id: str) -> str:
    return _join(outputs_root(user_id, work_id), MANIFEST_OUTPUTS)


def output_key(user_id: str, work_id: str, filename: str) -> str:
    leaf = _OUTPUTS_FILE_TEMPLATE.format(filename=filename)
    return _join(outputs_root(user_id, work_id), leaf)


# ── media/ (사용자 업로드 — work 레벨, presigned S3 직접. 메시지/chain 무관) ──


def media_root(user_id: str, work_id: str) -> str:
    return _join(session_root(user_id, work_id), NS_MEDIA)


def media_key(user_id: str, work_id: str, media_id: str, ext: str) -> str:
    """sessions/{user}/{work}/media/{media_id}.{ext}. writer = 브라우저(presigned PUT)."""
    leaf = _MEDIA_FILE_TEMPLATE.format(media_id=media_id, ext=ext)
    return _join(media_root(user_id, work_id), leaf)


# ── drawings/ (P-A 손 안 댐, builder 만 제공) ─────────────────────────────────


def drawings_root(user_id: str, work_id: str) -> str:
    return _join(session_root(user_id, work_id), NS_DRAWINGS)


def drawings_manifest_key(user_id: str, work_id: str) -> str:
    return _join(drawings_root(user_id, work_id), MANIFEST_DRAWINGS)


def drawing_dir(user_id: str, work_id: str, drawing_id: str) -> str:
    return _join(
        drawings_root(user_id, work_id),
        _DRAWINGS_PATH.format(drawing_id=drawing_id),
    )


def drawing_numerals_key(user_id: str, work_id: str, drawing_id: str) -> str:
    return _join(drawing_dir(user_id, work_id, drawing_id), _DRAWINGS_NUMERALS)


def drawing_dl_key(user_id: str, work_id: str, drawing_id: str) -> str:
    return _join(drawing_dir(user_id, work_id, drawing_id), _DRAWINGS_DL)


def drawing_figure_key(user_id: str, work_id: str, drawing_id: str) -> str:
    return _join(drawing_dir(user_id, work_id, drawing_id), _DRAWINGS_FIGURE)


# ── 레이아웃 파일명 상수 (public) — scaffolding 이 정의한 '사실' ────────────────
# key-builder 내부 + 구조검증(probe/_structure.py)이 공유. 검증 '로직' 은 여기 없음
# (probe 트랙 소속). 여기는 파일명/디렉토리명 사실만 노출 — literal 금지 원칙 유지.

CONVERSATION_FILE: Final[str] = _DRO_CONVERSATION_FILE
MEDIA_DIRNAME: Final[str] = NS_MEDIA
QUEUE_FILE: Final[str] = _PERSONA_QUEUE_FILE
CHAIN_MANIFEST_FILE: Final[str] = _PERSONA_CHAIN_MANIFEST
CHAIN_TRAIL_FILE: Final[str] = _PERSONA_CHAIN_TRAIL
CHAIN_RT_DIRNAME: Final[str] = _PERSONA_CHAIN_RT.split("/")[0]
CHAIN_AGENT_STATE_FILE: Final[str] = _PERSONA_CHAIN_AGENT_STATE
DRAWING_NUMERALS_FILE: Final[str] = _DRAWINGS_NUMERALS
DRAWING_DL_FILE: Final[str] = _DRAWINGS_DL
DRAWING_FIGURE_FILE: Final[str] = _DRAWINGS_FIGURE


__all__ = [
    "SCHEMA_VERSION",
    "ROOT_PREFIX",
    "ROOT_MANIFEST",
    "USERS_ROOT_PREFIX",
    "NS_RUNTIME",
    "NS_MODELS",
    "NS_DRAWINGS",
    "NS_OUTPUTS",
    "NS_MEDIA",
    "PERSONA_DIRS",
    "DRO_DIR",
    "MANIFEST_RUNTIME",
    "MANIFEST_MODELS",
    "MANIFEST_OUTPUTS",
    "MANIFEST_DRAWINGS",
    "IOM_FILE",
    "CMM_FILE",
    "USER_ROADMAP_FILE",
    "CONCEPT_DISCOVERY_STACK_FILE",
    "DIALOG_NAMES",
    # 레이아웃 파일명 사실 (구조검증이 공유)
    "CONVERSATION_FILE",
    "MEDIA_DIRNAME",
    "QUEUE_FILE",
    "CHAIN_MANIFEST_FILE",
    "CHAIN_TRAIL_FILE",
    "CHAIN_RT_DIRNAME",
    "CHAIN_AGENT_STATE_FILE",
    "DRAWING_NUMERALS_FILE",
    "DRAWING_DL_FILE",
    "DRAWING_FIGURE_FILE",
    # builders
    "persona_dir",
    "session_root",
    "identity_key",
    "profile_key",
    "idempotency_key",
    "refresh_token_key",
    "context_manifest_key",
    "runtime_root",
    "runtime_manifest_key",
    "dro_root",
    "conversation_key",
    "persona_root",
    "queue_key",
    "persona_dialog_key",
    "chain_dir",
    "chain_manifest_key",
    "trail_key",
    "rt_key",
    "agent_state_key",
    "models_root",
    "models_manifest_key",
    "iom_key",
    "cmm_key",
    "user_roadmap_key",
    "concept_discovery_stack_key",
    "outputs_root",
    "outputs_manifest_key",
    "output_key",
    "media_root",
    "media_key",
    "drawings_root",
    "drawings_manifest_key",
    "drawing_dir",
    "drawing_numerals_key",
    "drawing_dl_key",
    "drawing_figure_key",
]
