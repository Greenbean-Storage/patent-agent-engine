# `@knowledge/classification/` — IPC + CPC 분류 자산

## 출처 (9개, 다중 출처 merge)

| # | 자료 | 출처 | 한글 | 라이센스 |
|---|---|---|---|---|
| ① | WIPO IPC 트리 + Definitions | [ipcpub.wipo.int](https://ipcpub.wipo.int/) | ❌ | 무료, 저작권 명시 |
| ② | (위 ①에 포함) WIPO IPC Definitions | WIPO 공식 | ❌ | 동일 |
| ③ | KIPI IPC 한영 병렬 | [cls.kipro.or.kr/ipc](https://cls.kipro.or.kr/ipc) | ✅ | 한국특허정보원 공공 |
| ④ | KIPRIS Plus 변동이력 | [plus.kipris.or.kr](https://plus.kipris.or.kr/) | ✅ | 월 1,000건 무료 |
| ⑤ | 공공데이터포털 KSIC-IPC 연계표 | [data.go.kr](https://www.data.go.kr/) | ✅ | CC-BY-4.0 |
| ⑥ | WIPO Catchword Index | WIPO 공식 | ❌ | 동일 |
| ⑦ | CPC 트리 + Definitions | [cooperativepatentclassification.org](https://www.cooperativepatentclassification.org/) | ❌ | USPTO/EPO 공공 |
| ⑧ | KIPI CPC 한영 병렬 | [cls.kipro.or.kr/cpc](https://cls.kipro.or.kr/cpc) | ✅ | KIPI 공공 |
| ⑨ | WIPO IPC-CPC Concordance | WIPO 공식 | ❌ | 동일 |

각 빌드의 정확한 버전·다운로드 일시는 [version.json](version.json) 참조.

## 파일 구조

```
classification/
├── version.json                  # 빌드 메타 (출처별 URL · 다운로드 일시 · 버전)
├── ipc/
│   ├── tree.json                 # Section/Class/Subclass 메타 (한·영, ~3K 토큰)
│   └── subclasses/{XXXX}.json    # Subclass별 산하 Group/Subgroup 전체 (650 파일)
├── cpc/
│   ├── tree.json
│   └── subclasses/{XXXX}.json
├── ipc-cpc-concordance.json      # IPC ↔ CPC 매핑
├── catchwords.json               # 영어 키워드 → IPC
└── ksic-ipc.json                 # 한국 산업분류 ↔ IPC
```

`tree.json`은 LLM system_prompt에 직접 주입할 수 있는 가벼운 메타. `subclasses/{code}.json`은 분류 후보가 좁혀진 다음에만 동적으로 로드한다.

## 빌드

```bash
make build-classification          # 다중 출처 fetch → merge → verify → write
make build-classification-dry      # @knowledge/ 에 쓰지 않고 dry-run
make verify-classification         # 기존 산출물 검증 (노드 수·한글 커버리지)
```

빌더 코드: [`tools/classification-indexer/`](../../tools/classification-indexer/).

## 정책

- KIPI 사이트(cls.kipro.or.kr) 크롤링: robots.txt 전면 허용 확인 (2026-05-04). 자체 정책으로 User-Agent 명시 + 요청 간 1초 sleep + 사실적 분류 메타만 추출.
- 각 출처는 [version.json](version.json)에 URL · 다운로드 일시 명시.
