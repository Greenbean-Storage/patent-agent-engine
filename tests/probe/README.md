# tests/probe

## 목적
**실 CM 블랙박스** — 가동 중인 CM 을 외부에서 직접 호출해 chain / trail / RT / IOM / drawings / sessions 같은 자원을 (a) 동적 관찰, (b) 검증 환경 구성, (c) 동작·검증 상태 view, (d) CM 전 API 전수 + 실 S3 메모리 구조 검증 게이트. 관찰/구성/제어 도구 + `verify` 검증 게이트이며, play 가 `seed`/`check` 를 라이브러리로 import 사용. probe 는 라인-커버리지 트랙이 아니다 (그건 invoke) — `make probe cov` 없음.

## scope
- **CM 전용 검증** (CM 검증 역할): 9 invariants 정합 검사 (`check`)
- **검증 환경 구성** (환경 구성 역할): IOM PUT (`seed`), 세션·chain 목록·생성 등
- **동작·검증 상태 view** (view 역할): chain trail / RT / IOM / drawings read-only 표시
- **검증 게이트** (gate 역할): `verify` = CM 전 API 전수 호출 (`/openapi.json` 기반) + 실 S3 메모리 구조 ↔ scaffolding 대조. `exercise` = CM 모든 API 전수. `structure` = 세션 S3 구조 검증.

## sub-command tree
```
make probe view <chain_id>              # chain 전체 표시 (RT + trail + IOM + drawings)
make probe trail <chain_id>             # trail.jsonl stream
make probe check <chain_id>             # 9 invariants 정합 검사
make probe seed IOM=<path>              # IOM JSON CM 적재 (CM 동적 검증 도구)
make probe list [USER_ID=<id>]          # 세션 목록
make probe list-chains [USER_ID=<id>]   # chain 목록
make probe dump-rt <chain_id> <rt_id>   # 단일 RT 덤프
make probe models                       # models/ 산출물 표시
make probe dialogs                      # conversation 표시
make probe clean <work_id> YES=1        # invention 삭제 (DELETE, 되돌릴 수 없음)
make probe structure <work_id>          # 세션 S3 구조 ↔ scaffolding + manifest 대조
make probe exercise                     # CM 모든 API 전수 호출
make probe verify                       # 게이트 — CM 전 API 전수 + scaffolding 구조검증
```

## 의존
- `httpx>=0.28.0` (CM REST)
- `rich>=13.0.0` (표/트리 표시)
- `pyjwt>=2.13.0` — auth: OPEN 무토큰 / SECURE 공유 secret JWT mint (dev-token 폐기 — `_common.dev_token`)
- `venezia-shared` (editable — venezia_memory 레이아웃 상수·key-builder)
- docker stack (CM :59400 가동)

## 산출
sub-command 별 표시 (chain JSON, trail stream, invariants 결과, PUT 응답, 세션 목록). exit 0 / 1.

## play 와 관계
play (track 6) 가 probe.commands 의 `seed` / `check` 를 **라이브러리로 import** — play 의 `--seed-iom-from` 옵션, fixture mode 자동 invariants check 가 probe 라이브러리 활용. probe sub-command CLI 와 별개.

## 신트리 마이그레이션 완료 (2026-06-02)
구 endpoint(`/auth/dev-token`·`POST /api/v1/inventions`·`/inventions/{id}/draft{,/download}`)를 새 트리로 이전 — auth = OPEN 무토큰/SECURE mint(`_common.dev_token`·`_pipeline._dev_token`), session = `POST /api/v1/user/works`, draft = `POST·GET /api/v1/works/{id}/output/draft`. `commands.{seed,check}` import 경로·시그니처 불변(play 호환).
