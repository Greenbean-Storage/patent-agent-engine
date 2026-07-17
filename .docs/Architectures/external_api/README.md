# 외부 API 표준 명세 (INDEX)

> Next 웹 client 가 사용하는 **production 채널** API 의 표준 명세. **REST 와 WebSocket 을 분리한 두 표준 문서** 를 인덱스한다. 모든 client-facing REST + WebSocket + JWT 인증은 Nexus (100.Nexus, :59100) 가 단독 게이트웨이로 제공한다. DRO 는 내부 chain executor 로만 동작 — client REST/WS/auth/debug 표면이 없다 (단일 포트 `59200`, debug 포트 없음).

---

## 컨테이너 토폴로지

모든 client-facing 표면 (REST + WebSocket) 은 Nexus 단독. DRO 는 내부 chain executor 로 외부 노출 0:

| 컨테이너 | Port | 책임 영역 |
|---|---|---|
| `100.Nexus` | 59100 | 단독 외부 게이트웨이 — ALL client REST + client WebSocket + JWT 인증 |
| `200.DRO` (internal) | 59200 | 순수 내부 chain executor — `POST /control/spawn` + `POST /control/output` (IOM→DOCX) + `GET /events/{user_id}/{work_id}` (SSE) + `GET /health`. client REST/WS/media/auth 없음 |

외부 client 는 Nexus 단일 표면만 본다.

---

## 표준 문서

### REST — OpenAPI 정적 export

- [`openapi.nexus.json`](openapi.nexus.json) — Nexus REST (`:59100`) — 모든 client-facing endpoint 단독 제공 (Nexus 단독 spec — DRO client REST spec 없음)

`make export-openapi` 로 갱신:

```bash
make deploy init llm fake auth open && make up   # 4 컨테이너 가동 (FIXTURE + OPEN)
make export-openapi        # /api/v1/openapi.json fetch → .docs/Architectures/external_api/openapi.nexus.json
```

런타임에서 직접 보기도 가능:
- Nexus: `http://localhost:59100/api/v1/openapi.json` · Swagger UI `…/docs` (DRO 는 client REST 표면 없음 — OpenAPI spec 없음)

### WebSocket — AsyncAPI 3.0

- [`asyncapi.yaml`](asyncapi.yaml) — Nexus production WebSocket 양방향 명세 (host `nexus`, port `59100`)

검증:
```bash
npx -y @asyncapi/cli validate .docs/Architectures/external_api/asyncapi.yaml
```

---

## 메타 요구사항 (모든 표면 공통)

1. **최신 설계 반영** — 현행 설계만 기술.
2. **자원 영역 일관 설계** — info/auth/account/works/thread/estimate/media/output/system 경계가 path, event, 문서에서 동일.
3. **시퀀스 완성도** — 시작·진행·종료·복구 빠짐 없음.
4. **Progressive Disclosure** — endpoint 잘게 분리. 통합 1-call 은 sugar.
5. **AI 비식별** — 내부 역할·모델·실행 단위 식별자는 외부 표면(openapi/asyncapi/client 응답)에 노출하지 않는다. WS channel 라벨 6종 (`support`/`analysis`/`research`/`thinking`/`drafting`/`review`) 도 행위 중심.

이 5 메타 요구사항의 현행 *결과* 는 위 표준 문서(`openapi.nexus.json` · `asyncapi.yaml`)에 반영돼 있다. placeholder/잔재는 [`../../Issues/AUTH-REDESIGN-RESIDUALS.md`](../../Issues/AUTH-REDESIGN-RESIDUALS.md) · [`../../Issues/EXTERNAL-API-RESIDUALS.md`](../../Issues/EXTERNAL-API-RESIDUALS.md).

---

## 핵심 흐름 (요약)

### 1. 첫 진입
```
GET /api/v1/user/auth/{provider}/authorize         (Nexus)
→ (브라우저 OAuth)
→ /api/v1/user/auth/{provider}/callback?code&state (Nexus — 우리 JWT 발급)
GET /api/v1/user/account                           (Nexus)
GET /api/v1/user/works                              (Nexus — 목록)
POST /api/v1/user/works                             (Nexus — 새 work; 201 + Location)
WS /api/v1/works/{work_id}/thread/stream           (Nexus — httpOnly 쿠키 nx_access 자동 첨부)
```

### 2. 대화 사이클 (구체화 단계)
```
client → POST /api/v1/works/{id}/media {filename, mime} → 201 + Location, {media_id, url, fields}  (Nexus 인증 → CM 서명)
client → (브라우저가 url 로 S3 에 직접 POST — 바이트는 우리 서버 미경유. 미디어는 work 레벨, 메시지와 무관)
client → WS message.send {content, correlation_id}   (correlation_id=클라 멱등키; 재시도는 같은 값 재send)
server → WS message.received {correlation_id, id}     (acceptance ack, 송신 소켓에만; id=user turn 메시지 id; 후속 처리 완료 보장 아님)
server → WS work.progress {channel:"support", display_status: {ko:"발화 분석 중…"}}
server → WS work.progress {channel:"analysis", display_status: {ko:"진단 중…"}}
server → WS message.reply {id, text: "..."}            (id=최신 assistant turn 메시지 id)
server → WS model.maturity {overall_score, scores: {…}}
server → WS model.roadmap {count}
client → GET /api/v1/works/{id}/estimate/roadmap (fresh fetch)
```

### 3. 재진입 (새로고침·다음 날)
```
client → WS /api/v1/works/{id}/thread/stream?since_seq=N  (N>0이면 seq>N replay 요청. 단일 connection 재연결은 key GC로 보통 system.resync_required → REST refresh)
client → GET /api/v1/works/{id}                     (Nexus — 진입: work_id/title; 하위 자원은 고정 URL 템플릿으로 직접 구성, A-9)
client → GET /api/v1/works/{id}/meta               (Nexus — 상세 메타)
client → GET /api/v1/works/{id}/thread/messages    (Nexus — 대화 이력)
client → GET /api/v1/works/{id}/estimate/roadmap   (Nexus — 로드맵)
client → GET /api/v1/works/{id}/estimate/maturity  (Nexus — CMM 현재값)
```

### 4. 출원서 빌드·다운로드
```
client → POST /api/v1/works/{id}/output/draft          (현재 IOM을 DOCX로 동기 변환; 완료 알림은 WS output.ready)
server → WS output.ready {document_id, filename, size_bytes, download_url, preview_url}
client → GET /api/v1/works/{id}/output/draft/preview   (JSON, --- 마스킹)
client → GET /api/v1/works/{id}/output/draft           (docx full, 결제 게이트 통과 시)
```

---

## WS 채널 라벨 (6 baseline)

`work.progress.data.channel` 값:

| 라벨 | 의미 |
|---|---|
| `support` | 응대 |
| `analysis` | 구체화 진단 |
| `research` | 선행기술 조사 |
| `thinking` | 추론 |
| `drafting` | 작성 |
| `review` | 검토 |

매핑 single source: `shared/venezia_contracts/models/dro_api/channels.py:PERSONA_TO_CHANNEL` 의 dict 한 줄 수정으로 라벨 전체 변경 가능.

---

## 변경 정책

- **에러 envelope shape, WS envelope v2 shape, 이벤트 type enum**: 추가는 가능, 기존 type 의 data shape 변경은 break
- **`display_status`, `roadmap.items[].id`, `channel` 라벨 값**: 안정성 보장 (WS routing 은 (user_id, work_id) WS-key broadcast — `task_id` 없음)

---

## 후속·미구현 항목

자리만 잡혔거나 placeholder 인 항목 (현 트리 info/user/works 기준):
- `POST·GET /api/v1/works/{id}/output/proposal/{build,preview,download}` — **501 placeholder**. `draft/*`는 현재 IOM 기반 DOCX 변환/preview/download를 제공한다.
- `X-Payment-Token` / `X-Download-Gate` 결제 게이트 로직 (현재 통과)
- 자동 제목 생성 trigger
- 첨부 GC / presigned ticket expiry·idempotency 정책 (상세는 [`MEDIA-RESIDUALS.md`](../../Issues/MEDIA-RESIDUALS.md))
- mypage 통합 1-call (`GET /api/v1/user/account/me` 류, **미설계**)
- JWT refresh
- 등 — 상세는 issue 문서

각각 정합 동작 + 관련 파일·라인: [`../../Issues/EXTERNAL-API-RESIDUALS.md`](../../Issues/EXTERNAL-API-RESIDUALS.md)
