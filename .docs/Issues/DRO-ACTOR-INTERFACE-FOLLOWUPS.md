# DRO · Actor 인터페이스 — 후속 정리 후보

DRO·Actor 인터페이스의 **미결(open)** 정리 후보만 기록한다.

---

## 1. Cosmetic (low)

| # | 항목 | 증거 | 비고 |
|---|---|---|---|
| C1 | rt_error 관측 비대칭 — tool 실패는 `rt_error` 발사, LLM 전송실패는 미발사(chain `error` 만) | `200.DRO/src/orchestrator.py:521-537` vs `749-751` | 둘 다 Nexus 가 사용자에 숨김 — 내부 관측만 |
| C2 | `/health` 가 `llm_mode` 노출 (DRO 는 비-LLM 서비스) | `200.DRO/src/main.py:54-60` · `config.py:26-29` | by-design(운영자 profile 확인용) |
| C3 | SSE 구독자 큐 overflow oldest-drop, drop 신호 없음 | `200.DRO/src/event_sse.py:73-77` | best-effort 계약 부합(Nexus gap-detect + client refresh) |

---

## 결정 사항 (착수 전 확정)

1. **§1 cosmetic** — 손댈 것 선택(대부분 by-design).
