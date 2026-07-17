# 외부 API 표준

> 본 파일은 인덱스. **표준 명세 (REST + WebSocket 분리) 는 [`external_api/`](external_api/) 폴더 안에 있다.**
>
> 현행 트리 = `info / user / works`. user_id ⊥ JWT, federated 3-provider(PKCE S256), AUTH_MODE(OPEN|SECURE). 인증 = **httpOnly 쿠키**(`nx_access` 짧은 access + `nx_refresh` 회전; 콜백이 Set-Cookie+302; `/user/auth/refresh`·`/logout`). WS = `/api/v1/works/{work_id}/thread/stream`(nx_access 쿠키 자동 첨부). JSON 성공 응답은 typed `response_model`을 사용한다. 탐색 링크(HAL `_links`)는 제거됨(A-9) — 하위 자원 URL 은 고정 템플릿으로 클라가 직접 구성. 일부 dict request body는 OpenAPI에서 generic object로 남아 있다.

## 진실 원천

| 표면 | 표준 문서 | 산출 방법 |
|---|---|---|
| REST — Nexus (`:59100`) | [`external_api/openapi.nexus.json`](external_api/openapi.nexus.json) | `make export-openapi` (Nexus 가동 후 `/api/v1/openapi.json` fetch) |
| WebSocket — Nexus (`:59100`) | [`external_api/asyncapi.yaml`](external_api/asyncapi.yaml) | AsyncAPI 3.0 (수기, host `nexus:59100`) |
| 사용 흐름·메타 요구사항·변경 정책 | [`external_api/README.md`](external_api/README.md) | 수기 (narrative) |

## placeholder / 잔재 (후속)

| 자료 | 위치 |
|---|---|
| placeholder / 잔재 — 인증·UserID (결제게이트, proposal, SECURE e2e 등) | [`../Issues/AUTH-REDESIGN-RESIDUALS.md`](../Issues/AUTH-REDESIGN-RESIDUALS.md) |
| placeholder / 잔재 — 외부 API | [`../Issues/EXTERNAL-API-RESIDUALS.md`](../Issues/EXTERNAL-API-RESIDUALS.md) |
| 미디어 업로드/다운로드 (presigned lifecycle·idempotency·CORS·AI 소비 정책) | [`../Issues/MEDIA-RESIDUALS.md`](../Issues/MEDIA-RESIDUALS.md) |

## 검증

```bash
make export-openapi                                  # OpenAPI 정적 export
npx -y @asyncapi/cli validate external_api/asyncapi.yaml  # WS 명세 검증
make endpoint                                        # 11 phase REST + WS e2e (OPEN에서는 secure skip)
```

## 클라이언트 ⊥ 내부 표면

본 명세는 **Nexus (`:59100`) 단일 게이트웨이**의 클라이언트용 표면(REST + WebSocket)만 다룬다. DRO (`:59200`) 는 순수 내부 chain executor — 외부 표면 0. DRO 표면 = `{POST /control/spawn, POST /control/output(IOM→DOCX), GET /events/{user_id}/{work_id} (SSE), GET /health}` 전부 내부용이라 본 명세 범위 외 (Nexus output/draft 라우트가 docx 빌드를 `/control/output` 으로 위임). debug 표면(`/_debug/*`, `/api/v1/pipelines`, pipeline raw view, debug WS)은 외부에 없다 — DRO 는 단일 포트 `:59200`(별도 debug 포트 없음). dev/test pipeline trigger 는 DRO `POST /control/spawn` 직접 호출.
