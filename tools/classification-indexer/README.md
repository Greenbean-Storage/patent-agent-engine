# classification-indexer

`@knowledge/classification/` 정적 자산을 다중 출처에서 빌드한다.

## 출처 (9개)

| # | 자료 | 출처 | 모듈 |
|---|---|---|---|
| ① | WIPO IPC 트리 + Definitions | [ipcpub.wipo.int](https://ipcpub.wipo.int/) | `sources/wipo_ipc.py` |
| ② | WIPO IPC Definitions | WIPO 공식 별도 파일 | `sources/wipo_ipc.py` (병합) |
| ③ | KIPI IPC 한영 병렬 | [cls.kipro.or.kr/ipc](https://cls.kipro.or.kr/ipc) | `sources/kipi_ipc.py` |
| ④ | KIPRIS Plus 변동이력 | [plus.kipris.or.kr](https://plus.kipris.or.kr/) | `sources/kipris_plus.py` |
| ⑤ | KSIC-IPC 연계표 | [data.go.kr](https://www.data.go.kr/) | `sources/data_go_kr.py` |
| ⑥ | WIPO Catchword Index | WIPO 공식 | `sources/catchwords.py` |
| ⑦ | CPC 트리 + Definitions | [cooperativepatentclassification.org](https://www.cooperativepatentclassification.org/) | `sources/wipo_cpc.py` |
| ⑧ | KIPI CPC 한영 병렬 | [cls.kipro.or.kr/cpc](https://cls.kipro.or.kr/cpc) | `sources/kipi_cpc.py` |
| ⑨ | WIPO IPC-CPC Concordance | WIPO 공식 | `sources/concordance.py` |

## 빌드

```bash
cd tools/classification-indexer
uv sync --no-dev
uv run python -m classification_indexer build [--only ipc|cpc|all] [--cache .cache]
```

또는 프로젝트 루트에서:

```bash
make build-classification
```

결과는 `@knowledge/classification/` 에 기록된다.

## 단계

1. `fetch` — 각 출처에서 raw 데이터 다운로드. `.cache/` 에 저장 (gitignore).
2. `merge` — WIPO 트리를 마스터로 두고 KIPI 한글 라벨로 enrich, Definitions 첨부, KSIC·concordance·catchwords를 별도 파일로.
3. `verify` — 노드 수·schema·매핑 무결성 검증.
4. `write` — `@knowledge/classification/` 에 최종 JSON 기록.

## 정책

- KIPI 크롤링: User-Agent 명시, 요청 간 1초 sleep, robots.txt 준수.
- 모든 출처는 `version.json`에 기록 (URL · 다운로드 일시 · 버전).
- 사실적 분류 메타(코드·라벨·정의)만 추출. 사이트 디자인·해설문 미수집.
