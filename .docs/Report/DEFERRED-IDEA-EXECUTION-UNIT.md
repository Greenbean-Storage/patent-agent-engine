# 보류 아이디어 — 비-AI 실행 유닛 분리

상태: 아이디어. Tool Registry와 S3 작업 같은 비-AI 실행을 Actor/CM에서 별도 배포 유닛으로
분리할지 검토하는 문서다.

## 현재 구조

- **미디어**: Nexus가 work-level `POST /api/v1/works/{work_id}/media`에서 인증과 정책을 검사하고
  CM에 presigned S3 POST 서명을 요청한다. 바이트는 client/Actor와 S3 사이에서 직접 이동하며
  Nexus, DRO, CM을 통과하지 않는다.
- **툴**: Tool Registry는 `300.Actor/src/tools/`에 있고 DRO가
  `POST /tool/{name}`으로 Actor를 호출한다. AI 없는 실행이 Actor와 같은 배포 단위에 있다.

| 영역 | 현재 위치 | 근거 |
|---|---|---|
| 미디어 인증·정책 | Nexus | `100.Nexus/src/router.py:media_upload_url` |
| 미디어 서명·S3 목록/삭제 | CM | `400.CM/src/store.py:presign_put/presign_get/list_media/delete_media` |
| 미디어 영속 | S3 `sessions/{user}/{work}/media/{media_id}.{ext}` | `shared/venezia_memory.media_key` |
| Tool Registry | Actor | `300.Actor/src/tools/` |

## 분리 시 범위

- Tool Registry를 새 유닛으로 이전하고 DRO의 `/tool` 호출 대상을 변경한다.
- `engine.config tools.max_concurrency`의 소유권을 새 유닛으로 이동한다.
- presigned 서명·목록·삭제 책임을 새 유닛으로 옮길지 결정한다.
- actor:fake, kipris:fake, endpoint/invoke 검증 배치를 갱신한다.

## 제약

- 컨테이너 토폴로지와 내부 인증 경계가 바뀐다.
- 현재 S3 자격은 CM에만 있으므로 미디어 책임 이동은 자격 관리 변경을 동반한다.
- 미디어는 이미 work-level이라 chain admission과 독립이다.
- 현재 외부 인터페이스 위험은
  `../Issues/MEDIA-RESIDUALS.md`의 idempotency expiry/fingerprint와 CORS/cache 정책이다.

## 결정 필요 사항

1. 새 유닛 범위를 Tool Registry로 제한할지 미디어 작업까지 포함할지.
2. 내부 서비스명, 포트, 인증, timeout/retry 계약.
3. S3 자격과 presigned 책임을 CM에 유지할지 새 유닛으로 옮길지.
4. fake adapter와 검증 track의 소유권.
