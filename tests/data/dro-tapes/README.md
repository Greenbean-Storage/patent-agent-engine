# dro-tapes — mock-dro 의 RAW event tape 카탈로그 (CHUNK 4)

`dro:fake` 스택에서 mock-dro(`200.DRO/mocks/dro_app`) 가 spawn 수신 시 재생하는 사전 정의
RAW event 시퀀스. Nexus 의 **real** `event_mapper`/`ws_manager` 를 통과해 client WS envelope-v2
로 변환되므로, tape 하나 = Nexus 매핑 경로의 케이스 하나. compose 가 dro 서비스에
`/app/data/dro-tapes:ro` 로 mount (`.dockerignore` 가 `tests/` 제외 — bake 불가, fixtures 선례).

> **이벤트 매핑 (신 계약)** — event_mapper 분기:
> `rt_started`→**work.progress**(step 문구 forward + persona→channel) · `chain_completed(persona=1)`→**message.reply**(Nexus 가 CM conversation 에서 텍스트 생성) · `chain_completed(persona=2)`→**model.maturity/model.roadmap**(Nexus 가 CM fetch) · `rt_error`/`error`→**work.failed**(사용자 안전 메시지, raw 는 log). 그 외 RAW(`rt_enqueued`/`rt_progress`/`rt_result`)는 **사용자 미노출**(내부 관측). inbound `message.send`/`message.resend` 저장 ack = **message.received**(unicast).
> - **RT-시작 신호 = `rt_started`**(work.progress 유일 트리거). 구 tape 의 `rt_progress` 단독은 첫 건을 `rt_started` 로 승격.
> - **dro:fake 귀결**(mock CM r/w 0): `message.reply.text=null`(Nexus CM fetch 빈값) · **model.\* 미발생**(P02 tape 는 work.progress 만; model.\* 매핑 검증은 invoke·dro:real).

## 구조 / 재생 규약

- `{pipeline_id}/{NN-슬러그}.json` — **디렉토리 = pipeline_id (full id), 파일 정렬순 = playlist 재생순.**
- i번째 spawn 이 정렬순 i번째 tape 재생, **소진 시 마지막 반복**. cursor 키 = (user_id, work_id, pipeline_id) — endpoint phase 들이 각자 fresh work 를 쓰므로 phase 간 격리.
- engine=full 스택에선 message.send 1건이 P01+P02 두 spawn → 같은 인덱스의 두 tape 가 한 (user,work) 키에서 동시 재생 (seq 는 hub 가 per-key 단조 할당).

## tape 포맷

```json
{
  "description": "...",
  "events": [
    {"type": "rt_started", "persona": 1, "payload": {},
     "step": {"id": "s0", "display_status": {"ko": "시작", "en": "Working"}},
     "delay_ms": 0},
    {"type": "chain_completed", "persona": 1, "payload": {}}
  ],
  "expected": {
    "client_events": ["work.progress", "message.reply"],
    "forbidden": ["work.failed", "model.maturity", "model.roadmap", "output.ready"],
    "thinking_channels": ["support"],
    "client_event_counts": {"work.progress": 1, "message.reply": 1},
    "payload_contains": [
      {"type": "work.progress", "data": {"display_status": {"ko": "시작"}}},
      {"type": "message.reply", "data": {"text": null}}
    ]
  }
}
```

- **seq / timestamp / user_id / work_id / chain_id 는 tape 에 없음** — 재생 시점에 mock 이 할당/주입 (hard-coded seq 금지: P01+P02 가 한 키 공유).
- `payload` 는 full 운반 (4-2 — mock stateless, CM read/write 0; event_mapper 가 payload 만 forward).
- `expected` = endpoint `ws_tape` 러너의 기대값 (mock 은 무시) — 러너가 mapper 로직을 재구현하지 않고 여기서 read.
  - `client_events` ⊆ 수신 · `forbidden` ∩ 수신 = ∅ · `thinking_channels` ⊆ 관측 채널(= **work.progress** 이벤트의 channel). 수신 프레임은 봉투 스키마(C4, websocket-events.json)에도 검증.
  - **`forbidden` = 음성검증**: 이 tape 가 안 내는 신 contract 이벤트(`work.progress`/`message.reply`/`work.failed`/`model.maturity`/`model.roadmap`/`output.ready` − client_events). 러너가 P01∩P02 교집합으로 합성(한쪽이 정당히 내는 건 금지 불가). message.received(ack)·system.* 는 제외.
  - `client_event_counts` = type 별 **최소 건수** (매핑 drop 검출 — 같은 인덱스의 P01+P02 쌍은 러너가 합산).
  - `payload_contains` = 각 항목이 window 내 그 type 이벤트 중 ≥1건과 **부분일치**해야 함 (dict 재귀 subset, 빈 dict 는 정확히 빈 것, 그 외 동등) — event_mapper 의 내용 매핑(work.progress.display_status forward/fallback·channel·message.reply.text[dro:fake null]) 검증. type 존재만으론 broken mapper 가 통과 가능(Codex 지적)해서 추가된 계층.
- loader 는 **구조만** 검증 (type=str, payload=object) — RAW type enum 비강제 (unknown-type tape 가 mapper-skip 검증용으로 존재). 검증 실패 = mock 기동 crash (fail-loud — make up healthcheck 가 게이트).

## authoring 불변 (위반 시 phase 깨짐)

1. **idx 0 = happy-path** — `phase_ws`(비 tape phase) 의 message.send 가 소비, work.progress/message.reply hard assert (maturity/roadmap 는 dro:fake 미발생 — skip 규약).
2. **idx 1 = 무해** — 비 tape phase 는 fresh work 라 보통 idx 0 만 소비(message.resend 는 내용 dedup → 재spawn 없음). 여유분.
3. **마지막 tape = 무해** — 소진 반복분이 임의 후속 spawn 에 재생됨.
4. 확장 = JSON 추가만 (코드 0). 파일명 NN- prefix 로 재생순 제어.

## 현 카탈로그 (43)

- `P01.R00.CHAT_CONVERSATION/` (35): work.progress+message.reply happy · benign · rt_error/chain error → **work.failed** · rt_result 4변형 → message.reply만 · chain_completed 단독 → message.reply · unknown-type 생존 · multi-RT(work.progress 3) · persona 1~6 → work.progress.channel 전수 + null/범위밖 → support fallback · display_status forward/fallback 3종(ko-only/부재/비문자열) · rt_started/enqueued/progress 구분(시작 신호만 work.progress) · 장문/유니코드 result → message.reply · error+completed 공존 → work.failed+message.reply · 연속 error → work.failed×2 · 역순(stateless) · delay 타이밍 · 볼륨 · benign tail.
- `P02.R00.CONCEPT_MATURITY/` (8): happy → **정적 병렬 채점(step 2/3/4 동시, D-6) work.progress 3건(analysis)**; **model.\* 는 dro:fake 미발생**(CM 빈값 — 매핑은 invoke) · benign · maturity/roadmap 변형 전부 model.\* dro:fake skip · benign tail.

> **미생성**: 그 외 pipeline 의 playlist (P03 등 — Nexus 경유 spawn 은 P01/P02 뿐이라 현재 불요). 유저여정 시나리오 1급 재편 = NEXT-PLAN (`tests/endpoint/README.md` 참조).
