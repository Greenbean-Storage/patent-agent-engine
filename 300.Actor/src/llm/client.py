"""Gemini client singleton — embedding 등 raw client 호출용.

LlmAgent (chat) 의 client 는 google-adk 가 ENV 기반 자동 생성하므로 본 모듈을
거치지 않는다. 본 모듈은 KIPRIS RAG 등 embedding 호출이 매번 새 client 만드는
패턴을 통합하기 위한 thin singleton.

ENV (shared/venezia_secrets/__init__.py 가 AWS Secret 에서 자동 주입):
  GOOGLE_GENAI_USE_VERTEXAI=true
  GOOGLE_APPLICATION_CREDENTIALS=/tmp/google-credentials.json
  GOOGLE_CLOUD_PROJECT=<project_id>
  GOOGLE_CLOUD_LOCATION=global
"""

from __future__ import annotations

from functools import lru_cache

from google import genai


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    return genai.Client()
