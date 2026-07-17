# kipris-fixtures — KIPRIS canned 응답 (단일 소스)

`llm-fixtures` 의 형제. compose 가 전 actor 서비스에 `/app/data/kipris-fixtures:ro` 로 mount.

**소비자 2곳 (단일 소스 — drift 0)**:
1. **mock-actor `/tool` canned** (`300.Actor/mocks/actor_app/canned.py`, CHUNK 3-B) — `actor:fake` 에서 `kipris.search_patents` / `kipris.get_patent_detail` 가 이 데이터를 반환.
2. **real-actor `kipris:fake`** (`300.Actor/src/tools/kipris/fake.py`, via:config knob, CHUNK 3-C/3k 구현) — handler 가 `KIPRIS_MODE=fake` 면 같은 데이터를 read (실 API·키 불요). `make deploy set kipris fake` 로 선택 — 표준 로컬 레시피엔 비포함 (기본 real). 두 소비자의 의미론 동일: 전 query 가 pool[:n].

## 파일

| 파일 | shape | 비고 |
|---|---|---|
| `search_pool.json` | `[{application_number, title, applicant, application_date, abstract, ipc_codes}]` — 실 `KiprisClient.SearchResult.to_dict` 동형 | smart_beverage 특허 10건. application_number 세트 = `llm-fixtures/P03.R02.POST_REFLECT/0.json` 의 `ranked_patents` 와 동일 (thematic 일관). 전 query 가 같은 pool 을 받음 (canned 의미론) |
| `details.json` | `{app_no: {…PatentDetail.to_dict 동형…}}` | `kipris.get_patent_detail` lookup map. P03.R11 용 (default play 비경유) |

## 미생성 fixture / tool (NEXT-PLAN)

canned 범위 = default 파이프라인(smart_beverage: P01.R00 · P02.R00 · P03.R00·R01·R02)이 실제 호출하는 6 tool 만
(`staging.save` `maturity.compute` `roadmap.persist` `cm.append_conversation` `kipris.search_patents` `kipris.get_patent_detail`).
그 외 — P01.R1x/R2x/R4x (media_*), P02.R99 (미구현 target), P04~P06 (drawing.render / cm.save_drawing_artifacts /
knowledge.* 등) — 의 llm-fixture·canned tool 은 미생성: mock 에서 fixture miss = SSE error, tool 미등록 = 404 (strict fail-loud, 3g).
해당 pipeline 의 actor:fake 지원은 필요 시점에 fixture/canned 추가로 확장.
