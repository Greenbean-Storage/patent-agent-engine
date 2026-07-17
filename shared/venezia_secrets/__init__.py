"""AWS Secrets Manager loader — imported before config to inject env vars."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# SM 키 이름 → 앱이 기대하는 env var 이름 매핑.
# Identity 매핑 (key 와 env 가 동일) 도 등록 — secret 에 그 키가 존재함을 명시.
# Google Gemini 는 Vertex AI 전환 — API key 가 아니라 service account JSON 으로 인증.
# 별도 secret (llm-providers/prod/personal/google-credentials) 의 SecretString 이
# service account JSON 이면 _install_google_credentials 가 파일로 떨어뜨림.
_KEY_MAP: dict[str, str] = {
    "ANTHROPIC_KEY": "ANTHROPIC_API_KEY",
    "OPENAI_KEY": "OPENAI_API_KEY",
    "KIPRIS_KEY": "KIPRIS_API_KEY",
    "GOOGLE_CLIENT_ID": "GOOGLE_CLIENT_ID",
    # 아래 항목들은 env var 이름 매핑 — secret 값 자체 아님
    "GOOGLE_CLIENT_SECRET": "GOOGLE_CLIENT_SECRET",  # nosec B105
    # federated provider 확장 (Naver / Kakao)
    "NAVER_CLIENT_ID": "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET": "NAVER_CLIENT_SECRET",  # nosec B105
    "KAKAO_CLIENT_ID": "KAKAO_CLIENT_ID",
    "KAKAO_CLIENT_SECRET": "KAKAO_CLIENT_SECRET",  # nosec B105
    "JWT_SECRET_KEY": "JWT_SECRET_KEY",  # nosec B105
}

# Vertex ADC 가 약속한 경로 (GOOGLE_APPLICATION_CREDENTIALS 가 가리킴, chmod 600)
_GOOGLE_CREDENTIAL_PATH = "/tmp/google-credentials.json"  # nosec B108


def _install_google_credentials(secret_data: dict) -> None:
    """Service account JSON 을 파일로 저장하고 Vertex AI 용 ENV 자동 설정.

    google-auth ADC chain 이 GOOGLE_APPLICATION_CREDENTIALS 파일을 자동 인식.
    """
    import json

    path = _GOOGLE_CREDENTIAL_PATH
    with open(path, "w", encoding="utf-8") as f:
        json.dump(secret_data, f)
    os.chmod(path, 0o600)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    project_id = secret_data.get("project_id")
    if project_id:
        os.environ["GOOGLE_CLOUD_PROJECT"] = str(project_id)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"


def _load() -> None:
    raw = os.getenv("AWS_SECRET_NAME", "").strip()
    mode = (os.getenv("MODE") or "").upper()
    if not raw:
        # MODE=PRODUCTION 인데 AWS_SECRET_NAME 미설정 = compose 설정 오류 → fail-loud.
        # FIXTURE 등 다른 모드는 secret 없이 동작.
        if mode == "PRODUCTION":
            raise RuntimeError(
                "PRODUCTION mode 인데 AWS_SECRET_NAME 미설정 — compose.yaml 점검 필요."
            )
        return
    secret_names = [s.strip() for s in raw.split(",") if s.strip()]
    try:
        import json

        import boto3

        client = boto3.client(
            "secretsmanager",
            region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        )
        injected = 0
        for secret_name in secret_names:
            resp = client.get_secret_value(SecretId=secret_name)
            secret_data: dict = json.loads(resp["SecretString"])

            # Google service account JSON 은 파일로 떨어뜨림 (Vertex AI ADC).
            if isinstance(secret_data, dict) and secret_data.get("type") == "service_account":
                _install_google_credentials(secret_data)
                injected += 1
                continue

            for sm_key, value in secret_data.items():
                env_key = _KEY_MAP.get(sm_key, sm_key)
                # 빈 문자열(compose 의 `${VAR:-}` default)도 미설정으로 간주 —
                # AWS Secrets 가 .env fallback 보다 우선.
                if not os.environ.get(env_key):
                    os.environ[env_key] = str(value)
                    injected += 1
        log.info("aws_secrets.loaded secrets=%s injected=%d", secret_names, injected)
        print(
            f"[venezia_secrets] loaded secrets={secret_names} injected={injected}",
            flush=True,
        )
    except Exception as exc:
        # silent fallback 금지 — secrets 못 가져오면 startup 자체 실패시킨다.
        # AWS Secrets 가 늦으면 컨테이너 healthcheck 가 재시도하므로 정상 흐름 보장.
        if mode == "PRODUCTION":
            print(
                f"[venezia_secrets] FATAL secrets fetch failed: {exc}\n"
                "  → PRODUCTION 모드는 EC2 IAM role 환경 전제입니다.\n"
                "  → 로컬 dev 는 'make deploy init llm fake auth open && make up' (FIXTURE).",
                flush=True,
            )
        else:
            print(f"[venezia_secrets] FATAL secrets fetch failed: {exc}", flush=True)
        raise


_load()
