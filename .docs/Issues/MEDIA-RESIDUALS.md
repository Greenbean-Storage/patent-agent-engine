# 미디어 외부 인터페이스와 후속 작업

현재 미디어 표면의 사실과 남은 작업을 기록한다.

## 현재 구조

1. 업로드와 다운로드 바이트는 client/Actor와 S3 사이에서 직접 이동한다.
2. Nexus가 JWT와 work 존재, MIME, 파일 수 상한을 검사한다.
3. CM이 유일한 S3 자격 보유자로서 presigned POST/GET을 서명한다.
4. 미디어는 work-level 자원이며 키는
   `sessions/{user}/{work}/media/{media_id}.{ext}`다.
5. 별도 media 장부 없이 S3 prefix와 object metadata가 목록의 진실 원천이다.
6. 크기와 MIME은 presigned POST policy로 S3가 강제한다.

## REST 표면

- `POST .../media {filename, mime}` → 201 `PresignUploadResponse` + `Location`
- `GET .../media` → `MediaListResponse`
- `GET .../media/{media_id}` → `MediaDownloadResponse`
- `DELETE .../media/{media_id}` → 204

## 현재 후속 작업

- **Idempotency record 수명**: 완료 record가 presigned upload URL과 fields를 만료 없이 보존한다.
  같은 key의 재시도는 URL TTL 이후에도 만료된 ticket을 재생할 수 있다.
- **Request fingerprint 부재**: 같은 key로 filename/mime이 다른 요청을 보내도 최초 응답을 반환한다.
- **Finalize ambiguity**: ticket 발급 후 완료 record 저장이 실패하면 재시도에서 다른 media_id가
  발급될 수 있다.
- **목록 경쟁**: `max_files_per_work`는 list 후 ticket 발급이라 동시 요청에서 상한을 초과할 수 있다.
- **민감 응답 cache**: presigned URL 응답에 명시적 `Cache-Control: no-store`가 없다.
- **S3 CORS**: 브라우저 직접 POST/GET을 허용하는 production origin 정책이 필요하다.
- **AI 소비 정책**: file access tool을 허용할 persona와 MIME별 처리 정책을 정의해야 한다.

권장 계약:

- idempotency record에 request fingerprint와 response expiry를 저장한다.
- 만료된 upload ticket 재시도는 새 ticket을 발급하거나 명시적 409로 처리한다.
- 완료 record와 media allocation을 재개 가능한 operation state로 관리한다.
- presigned URL을 포함한 응답에 `Cache-Control: no-store`를 적용한다.

## 운영 설정

`@deployment/media.config.yaml`:

- `max_file_bytes=20 MiB`
- MIME: JPEG, PNG, WebP, GIF, PDF
- `max_files_per_work=50`
- upload TTL 600초
- download TTL 300초
