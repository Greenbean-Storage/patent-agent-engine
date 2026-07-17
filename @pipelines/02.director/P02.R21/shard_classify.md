# P02.R21.CLASSIFY_SHARD :: shard_classify

> shard 내에서 본 발명과 관련성 높은 IPC 후보 분류 list 추출 — parent 의 merge_candidates 입력.

## Instructions

**1. shard 담당 영역 인지**: context.inputs.shard_code 확인 — 'AB' (Section A: 생활필수품 / B: 운수·기계조작), 'CD' (C: 화학·야금 / D: 섬유·종이), 'EF' (E: 건설·광산 / F: 기계공학·조명·난방·무기·폭파), 'GH' (G: 물리 / H: 전기). 발명 도메인이 본 shard 와 부합도가 낮으면 즉시 빈 배열로 종료.

**2. 분류 트리 메타 분석**: context.steps.load_shard.ipc / cpc 에 담긴 Section→Class→Subclass 의 title 을 invention_summary 와 의미적 매칭. Subclass 까지만(예: 'A47G' 의 4글자) 좁힘 — Group/Subgroup 결정은 다음 정밀 단계(pinpoint_group) 가 담당.

**3. ipc_candidates 선정 (0~5개)**: invention_summary 의 핵심 기술 도메인과 부합하는 Subclass. 각 후보 = {code: 'A47G', rationale: '음료 용기 및 식기와 직접 부합'}. 무관하면 빈 배열. 1~2개가 일반적, 3~5개는 발명이 본 shard 의 여러 분야를 걸칠 때.

**4. cpc_candidates 선정 (0~5개)**: CPC 는 IPC 와 거의 일치하나 EPO/USPTO 가 더 세분화한 그룹이 있을 수 있음. 본 shard 의 CPC 트리에서 invention_summary 와 매칭되는 Subclass 후보. 한국 출원만 의도하면 빈 배열도 무방.

**5. rationale 작성 (1줄)**: 매칭의 핵심 단서 1줄 — '발명의 음료 용기 + 온도 표시 측면과 직접 부합' / '발명의 IoT 통신 측면 — 광범위 매칭'. 추상적 표현 금지.

**6. false-positive 회피 (핵심 원칙)**: 본 shard 의 keyword 가 invention_summary 에 우연히 포함된 경우(예: '용기' 라는 단어가 화학 분야 발명에 우연 등장) 후보로 선정하지 말 것. 발명의 본질이 본 shard 의 분야에 속해야 함. 의심스러우면 빈 배열.

**7. 보수적 큐레이션**: 통합 단계(merge_candidates) 가 4 shard 결과를 종합하므로, 본 shard 가 무관하면 빈 결과 → 정답이 다른 shard 에서 나옴. 잘못 채워서 통합 단계 attention 분산시키는 게 더 큰 손실.

## Output Contract

`shortlist-in-shard-output`
