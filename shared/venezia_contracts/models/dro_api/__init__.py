"""DRO 외부 API (REST + WS) 의 Pydantic 모델 (손작성).

외부 표면 (web client 가 보는 모양) 전용 subpackage.

모듈별 책임:
- error: 단일 에러 envelope + ErrorCode enum
- channels: persona→channel 매핑 (PERSONA_TO_CHANNEL)
- message: 대화 이력 item (MessageHistoryItem)
- work_api / account_api / upload: 현행 client REST 응답 모델
- document: 출원서 빌드·다운로드 (output 마일스톤, 미배선)
"""
