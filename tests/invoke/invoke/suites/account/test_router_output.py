"""100.Nexus output 라우트 — draft build/preview/download + proposal 501 (invoke 단위, ≥99% line).

대상: 100.Nexus/src/router.py 의 C6 output 핸들러 + 헬퍼
(_DOCX_MEDIA_TYPE / _require_payment / _mask_substring / _claims_masked):
  draft_build    : POST .../output/draft → control_output(DRO) → {document_id,filename,size_bytes}
                   + last_activity_at 패치 · DRO content_not_ready(404) 전파 · 빈 결과 fallback
  draft_preview  : GET  .../output/draft/preview (마스킹 dict; iom None→404; claims 3분기) — 경로 불변
  draft_download : GET  .../output/draft (present→docx Response / absent→404)
  proposal_*     : build(POST)/preview(GET)/download(GET) = 501 not_implemented (라우트 OPEN·로직 미구현)

control_output(dro_client) 와 get_cm_client 를 monkeypatch. auth 는 dependency_overrides.
async 는 asyncio.run(...) (suite 패턴).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "@pipelines").is_dir())
sys.path.insert(0, str(ROOT / "100.Nexus"))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from src import errors  # noqa: E402
from src import router as router_mod  # noqa: E402
from src.auth import get_current_user  # noqa: E402
from src.router import router  # noqa: E402

_UID = "u-1"
_WORK = "work-1"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _FakeCM:
    """output 라우트 용 fake CM — get_iom/download_document/patch_context_manifest 기록."""

    def __init__(self, *, iom=None, doc=None) -> None:
        self._iom = iom
        self._doc = doc
        self.patch_calls: list[tuple] = []
        self.download_calls: list[tuple] = []

    async def get_iom(self, user_id, work_id, pointer=""):
        return self._iom

    async def download_document(self, user_id, work_id, filename):
        self.download_calls.append((user_id, work_id, filename))
        return self._doc

    async def patch_context_manifest(self, user_id, work_id, ops):
        self.patch_calls.append((user_id, work_id, ops))
        return {}


def _build_app(monkeypatch, *, cm=None, control_output=None, user=None):
    app = FastAPI()
    errors.install(app)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: (user or {"user_id": _UID})
    if cm is not None:
        monkeypatch.setattr(router_mod, "get_cm_client", lambda: cm)
    if control_output is not None:
        monkeypatch.setattr(router_mod, "control_output", control_output)
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _run(coro):
    return asyncio.run(coro)


def _post(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.post(url, **kw)

    return _run(go())


def _get(app, url, **kw):
    async def go():
        async with _client(app) as c:
            return await c.get(url, **kw)

    return _run(go())


# ── draft/build ──────────────────────────────────────────────────────────────


def test_draft_build_calls_dro_returns_and_patches(monkeypatch):
    out_calls: list[tuple] = []

    async def _control_output(user_id, work_id, variant):
        out_calls.append((user_id, work_id, variant))
        return {"document_id": "draft", "filename": "draft.docx", "size_bytes": 4096}

    cm = _FakeCM()
    app = _build_app(monkeypatch, cm=cm, control_output=_control_output)
    r = _post(app, f"/api/v1/works/{_WORK}/output/draft")
    assert r.status_code == 200  # 동기 placeholder — 결과(filename/size) 본문 반환
    body = r.json()
    assert body["filename"] == "draft.docx"
    assert body["size_bytes"] == 4096  # A-7: WS output.ready 와 동일 필드명
    assert body["document_id"] == "draft"
    assert out_calls == [(_UID, _WORK, "draft")]
    # last_activity_at 패치 1건 (mypage 메타 — Nexus 소유)
    assert len(cm.patch_calls) == 1
    _, _, ops = cm.patch_calls[0]
    assert ops[0]["path"] == "/last_activity_at"


def test_draft_build_empty_dro_result_fallbacks(monkeypatch):
    async def _control_output(user_id, work_id, variant):
        return {}

    cm = _FakeCM()
    app = _build_app(monkeypatch, cm=cm, control_output=_control_output)
    r = _post(app, f"/api/v1/works/{_WORK}/output/draft")
    assert r.status_code == 200  # 빈 DRO 결과 → fallback {draft, draft.docx, 0}
    body = r.json()
    assert body["filename"] == "draft.docx"
    assert body["size_bytes"] == 0
    assert body["document_id"] == "draft"


def test_draft_build_content_not_ready_404(monkeypatch):
    from src.errors import APIError
    from venezia_contracts.models.dro_api.error import ErrorCode

    async def _control_output(user_id, work_id, variant):
        raise APIError(ErrorCode.content_not_ready, 404, "작성 콘텐츠 미준비")

    cm = _FakeCM()
    app = _build_app(monkeypatch, cm=cm, control_output=_control_output)
    r = _post(app, f"/api/v1/works/{_WORK}/output/draft")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "content_not_ready"
    # control_output 실패 → patch 미발생
    assert cm.patch_calls == []


# ── draft/preview ────────────────────────────────────────────────────────────

# 실 IOM schema 모양 (사용자 결정: schema 정본). title={ko,en} dict — 구 500 경로 재현.
_PREVIEW_IOM = {
    "bibliographic": {
        "title": {"ko": "스마트 음료 용기", "en": "Smart Beverage Container"},
        "filing_type": "domestic",
    },
    "abstract": {"text": "초" * 200},
    "specification": {
        "technical_field": "기" * 200,  # schema: str (nested under specification)
        "background_art": {"description": "배" * 100},  # schema: {description}
        "detailed_description": "명" * 100,  # schema: str
    },
    "claims": [  # schema: list[{number, type, text}]
        {"number": 1, "type": "independent", "text": "청" * 60},
        {"number": 2, "type": "dependent", "text": "구"},
        {"text": "", "body": "본문대체"},
        "plain-claim",
        {},
    ],
}

_MASKED = "(다운로드 시 전체 공개)"


def test_draft_preview_masks_sections(monkeypatch):
    cm = _FakeCM(iom=_PREVIEW_IOM)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft/preview")
    assert r.status_code == 200  # ★ dict title 이 더 이상 500 아님 (회귀 가드)
    body = r.json()
    assert body["title"] == "스마트 음료 용기"  # {ko,en}→ko, 공개·무마스킹
    assert body["abstract"].endswith(_MASKED)  # 200>80
    assert body["technical_field"].endswith(_MASKED)  # spec.technical_field str, 200>80
    assert body["background"].endswith(_MASKED)  # background_art.description, 100>60
    assert body["specification"].endswith(_MASKED)  # detailed_description, 100>40
    claims = body["claims"]
    assert len(claims) == 5
    assert claims[0].endswith(_MASKED)  # text 60>30
    assert claims[1] == "구"  # text ≤30 → 원문
    assert claims[2] == "본문대체"  # text "" → body fallback
    assert claims[3] == "plain-claim"  # str(c)
    assert claims[4] == "---"  # 빈 → "---"
    assert set(body["sections_present"]) == {
        "title",
        "abstract",
        "technical_field",
        "background",
        "specification",
        "claims",
    }


def test_draft_preview_short_and_absent_sections(monkeypatch):
    # 짧은 필드 → 원문. title·background·claims 부재 → None.
    iom = {"abstract": {"text": "짧은 초록"}, "specification": {"technical_field": "짧음"}}
    cm = _FakeCM(iom=iom)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft/preview")
    assert r.status_code == 200
    body = r.json()
    assert body["abstract"] == "짧은 초록"  # ≤80 → 원문
    assert body["technical_field"] == "짧음"  # ≤80 → 원문
    assert body["title"] is None and body["background"] is None and body["claims"] is None
    assert set(body["sections_present"]) == {"abstract", "technical_field"}


def test_draft_preview_str_title_and_nonconforming_no_500(monkeypatch):
    # title 이 plain str(방어) → 그대로. 비-str spec 필드(스키마 위반)·비-list claims → mask None, 500 아님.
    iom = {
        "bibliographic": {"title": "문자열 제목"},
        "specification": {"technical_field": {"ko": "비정합"}, "detailed_description": 123},
        "claims": "not-a-list-or-dict",
    }
    cm = _FakeCM(iom=iom)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft/preview")
    assert r.status_code == 200  # isinstance 가드 — 비정합에도 500 안 남
    body = r.json()
    assert body["title"] == "문자열 제목"  # str title 통과
    assert body["technical_field"] is None  # dict → 마스킹 None
    assert body["specification"] is None  # int → 마스킹 None
    assert body["claims"] is None  # str → _claims_masked None


def test_draft_preview_claims_dict_items_not_list_none(monkeypatch):
    # claims 가 dict 이고 items 가 list 아님 → None (구 {items} 형태 흡수 경로).
    cm = _FakeCM(iom={"claims": {"items": "not-a-list"}})
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft/preview")
    assert r.status_code == 200
    assert r.json()["claims"] is None


def test_draft_preview_iom_missing_404(monkeypatch):
    cm = _FakeCM(iom=None)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft/preview")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "content_not_ready"


# ── draft/download ───────────────────────────────────────────────────────────


def test_draft_download_present(monkeypatch):
    cm = _FakeCM(doc=b"DOCXBYTES")
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft")
    assert r.status_code == 200
    assert r.content == b"DOCXBYTES"
    assert r.headers["content-type"] == _DOCX_MIME
    assert 'attachment; filename="draft.docx"' in r.headers["content-disposition"]
    assert r.headers["x-download-gate"] == "placeholder"
    assert cm.download_calls == [(_UID, _WORK, "draft.docx")]


def test_draft_download_absent_404(monkeypatch):
    cm = _FakeCM(doc=None)
    app = _build_app(monkeypatch, cm=cm)
    r = _get(app, f"/api/v1/works/{_WORK}/output/draft")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "document_not_ready"


# ── proposal/* → 501 (라우트 OPEN·로직 미구현, 후속 마일스톤) ───────────────────


def test_proposal_build_501(monkeypatch):
    app = _build_app(monkeypatch)
    r = _post(app, f"/api/v1/works/{_WORK}/output/proposal/build")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"


def test_proposal_preview_501(monkeypatch):
    app = _build_app(monkeypatch)
    r = _get(app, f"/api/v1/works/{_WORK}/output/proposal/preview")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"


def test_proposal_download_501(monkeypatch):
    app = _build_app(monkeypatch)
    r = _get(app, f"/api/v1/works/{_WORK}/output/proposal/download")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "not_implemented"
