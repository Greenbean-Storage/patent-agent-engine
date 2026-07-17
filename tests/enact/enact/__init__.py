"""enact — 검증 track 5: Actor 가 단일 RT 를 수행(enact)하는 것을 격리 검증.

UUT = real Actor 1 컨테이너 (actor:real) · harness = DRO 역할 대행
(POST /dispatch + SSE 소비 · POST /tool/{name}) · mock-below = llm:fake + real CM.
설계·사용법 = tests/enact/README.md.
"""
