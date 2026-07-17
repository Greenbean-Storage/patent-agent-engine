"""dro:fake mock 앱 — via:image knob dro=fake (DRO_TARGET=mock) 일 때 기동.

실 DRO internal 표면({POST /control/spawn, GET /events/{u}/{w} SSE,
GET /health})의 mock 구현. spawn 수신 시 pipeline_id 별 playlist 의 다음 tape 를
열린 /events 연결로 재생 — Nexus 의 real event_mapper/ws_manager 를 결정적으로 검증.
모듈 구성은 `app.py` docstring 참조.
"""

__version__ = "0.1.0"
