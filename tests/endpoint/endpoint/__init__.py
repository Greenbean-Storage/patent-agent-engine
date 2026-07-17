"""endpoint — 검증 track 7.

docker stack 의 DRO 가 가동된 상태에서 외부 API 표면 (REST + WS) 을 phase 단위로
호출하여 응답 contract (status / shape / error envelope / WS envelope v2) 검증.
외부 사용자 관점 진짜 e2e. Make: `make endpoint [<phase>]`.
"""

__version__ = "0.1.0"
