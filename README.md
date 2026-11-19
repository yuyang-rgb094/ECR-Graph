# ECR-Graph

**Evidence-governed engineering-change graphs for medical-device teams.**
**面向医疗器械团队、以证据为约束的工程变更图谱工具包。**

[English](#english) · [中文](#中文)

> **Candidates only, never verdicts.** ECR-Graph produces review candidates. Judgements such as "compliant", "released" or "no registration change" are made and recorded by the user's designated RA, QA and document-control staff.
>
> **只产候选，不下结论。** ECR-Graph 只输出审查候选。“合规”“放行”“不涉及注册变更”这类判断，由使用方指定的 RA、QA 和文控人员作出并记录。

---

## English

### What it is

ECR-Graph is a small, offline-capable Python toolkit for teams that handle engineering change requests (ECRs) and controlled documents. A user's AI agent can install and run it end to end:

parsing → entity extraction → dedupe → conservative disambiguation → graph building → deterministic checks → conflict ledger → document association & cross-review → **change-content sufficiency review** → **registration-impact pre-assessment** → grilling the user for experience and evidence

- Python standard library only, Python ≥ 3.9. MinerU, LibreOffice and pypdf are optional.
- Every assertion carries an evidence locator: derived-text path, line numbers, quote, and the SHA-256 of the original file.
- No company, product or regulatory instance is built in. Regulatory experience comes from the user's own knowledge pack, and every entry must cite its source.

### Quick start

```bash
python3 -m ecr_graph demo ./demo                 # generate a fully fictional demo project
python3 -m ecr_graph run -c ./demo/ecr-graph.json
python3 -m ecr_graph regimpact -c ./demo/ecr-graph.json --proposal ./demo/proposals/PRP-001.json
python3 -m ecr_graph export -c ./demo/ecr-graph.json      # GraphML / Neo4j CSV / Obsidian
python3 -m unittest discover -s tests                     # regression tests (synthetic data)
```

For your own project:

```bash
python3 -m ecr_graph init ./my-project
# sources/   ECR forms (.doc/.docx/.pdf), treated as read-only
# revised/   revised versions of affected documents (needed for sufficiency review)
# knowledge/ your experience: inspection checklist, inspection findings, registration items, software version rule ...
python3 -m ecr_graph run -c ./my-project/ecr-graph.json
```

### Commands

| Stage | Command | Output |
|---|---|---|
| Parse | `ingest` | line-numbered derived text `work/text/*.txt` (table rows tagged `[T#R#]`); `manifest.json` with file hashes, parser and warnings |
| Extract | `extract` | ECRs, change points (`CP-<ECR>-S01P02`), attachment-table rows, document versions, product labels |
| Dedupe / disambiguate | `resolve` | merges evidence of identical triples; `same_as` only from human adjudication; labels differing only by a bracketed qualifier become `possible_identity` |
| Check | `check` | coverage, dangling edges, quote verification, unresolved references, version-chain gaps / reversals / repeats |
| Association & cross-review | `crossref` | document association table (co-changed in a change point, co-changed in an ECR, text references, companion rules) and findings for missing companion documents |
| Sufficiency review | `sufficiency` | stale old values, missing new values, missing class-required content, undeclared new version; semantic review packets for the user's agent |
| Registration-impact pre-assessment | `regimpact` | compares a *proposed* change, dimension by dimension, with registration items and the software version rule; four candidate outcomes, open questions and redesign directions to discuss with RA |
| Five-axis index | `axes` | change events / product configurations / engineering objects / controlled files / impact relationships, each loadable on its own |
| Grill | `grill` | prioritised questions and a document request list driven by knowledge gaps (`grill.md`) |
| Multi-source merge | `candidates`, `merge` | imports agent candidates (evidence must verify verbatim); merges as base package + candidate projections; conflicts go to a ledger |
| Read & query | `export`, `mcp` | GraphML, Neo4j CSV, Obsidian vault; read-only MCP server |
| Pre-release self-check | `leakscan` | private denylist plus generic sensitive-pattern scan |

### Design principles

1. **Evidence before conclusions** — candidates without verifiable evidence are rejected, never silently kept.
2. **Layered assertions** — `source_assertion` / `rule_derived` / `external_corroboration` / `cross_source_candidate` / `human_adjudication`.
3. **No majority voting** — one source is the base package; the others are candidate projections; disagreements go to the conflict ledger.
4. **No record ≠ does not exist** — counts describe only this batch under these rules.
5. **Ask for experience** — when the inspection checklist, findings or registration content is missing, the toolkit asks for it instead of pretending a generic example is the answer.

### Large documents

Files over 50 MB, image-heavy files, PDFs and scans are routed to MinerU. Local deployment is preferred; the cloud API requires explicit upload consent in the project config. The cloud tier gives 1,000 pages per day at top priority, with at most 200 MB / 200 pages per file. See [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md).

For legacy `.doc` files, install LibreOffice. macOS `textutil` works as a fallback but drops or flattens some tables.

### Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — data contracts, modules and decision boundaries
- [docs/AGENT-PLAYBOOK.md](docs/AGENT-PLAYBOOK.md) — agent workflow and grill protocol
- [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md) — MinerU local deployment and cloud API key
- [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md) — redaction and licence checks before release
- [skills/ecr-graph/SKILL.md](skills/ecr-graph/SKILL.md) — a skill file to install into an agent

*Detailed docs are currently in Chinese; English translations are welcome.*

### Status & licence

Version `0.1.0`, early release. Licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE). Optional components are not bundled and keep their own licences: MinerU (MinerU Open Source License, Apache 2.0 based with additional terms), LibreOffice (MPL-2.0), pypdf (BSD-3-Clause).

---

## 中文

### 这是什么

ECR-Graph 是一个可离线运行的小型 Python 工具包，面向需要处理工程更改（ECR）和受控文件的团队。使用方的 Agent 可以自行安装，并从头到尾跑完：

文档解析 → 实体抽取 → 去重 → 保守消歧 → 图谱构建 → 确定性校验 → 冲突归集 → 文档关联与交叉审核 → **变更内容充分性审查** → **注册影响预评估** → 向使用方追问经验与资料（Grill）

- 只依赖 Python 标准库，支持 Python ≥ 3.9。MinerU、LibreOffice、pypdf 为可选组件。
- 每条断言都带证据定位：派生文本路径、行号、原文摘要，以及原件的 SHA-256。
- 不内置任何企业、产品或法规实例。法规经验由使用方以自己的知识包提供，每条都须注明来源。

### 快速开始

```bash
python3 -m ecr_graph demo ./demo                 # 生成一个完全虚构的示例项目
python3 -m ecr_graph run -c ./demo/ecr-graph.json
python3 -m ecr_graph regimpact -c ./demo/ecr-graph.json --proposal ./demo/proposals/PRP-001.json
python3 -m ecr_graph export -c ./demo/ecr-graph.json      # GraphML / Neo4j CSV / Obsidian
python3 -m unittest discover -s tests                     # 回归测试（虚构数据）
```

在自己的项目中使用：

```bash
python3 -m ecr_graph init ./my-project
# sources/   放 ECR（.doc/.docx/.pdf），只读
# revised/   放受影响文件的更改后版本（做充分性审查需要）
# knowledge/ 放使用方经验：考纲条款、飞检发现、注册内容、软件版本规则……
python3 -m ecr_graph run -c ./my-project/ecr-graph.json
```

### 命令一览

| 阶段 | 命令 | 产出 |
|---|---|---|
| 解析 | `ingest` | `work/text/*.txt` 行号化派生文本（表格行带 `[T#R#]`），`manifest.json` 记录原件哈希、解析器和告警 |
| 抽取 | `extract` | ECR、更改点（`CP-<ECR>-S01P02`）、附表文件行、文件版本、型号标签 |
| 去重/消歧 | `resolve` | 合并相同三元组的证据；`same_as` 只能来自人工裁决；仅括号限定不同的标签生成 `possible_identity` |
| 校验 | `check` | 覆盖、悬空边、原文摘要、未解析引用、版本链断点/回退/重复 |
| 关联与交叉审核 | `crossref` | 文档关联关系表（同更改点共改、同 ECR 共改、正文互引、配套规则）及缺失配套文件的发现 |
| 充分性审查 | `sufficiency` | 旧值残留、新值缺失、文件类别应含内容缺失、未声明新版本；另生成语义审查包，交给使用方的 Agent |
| 注册影响预评估 | `regimpact` | 对*方案阶段*的变更逐维度比对注册内容和软件版本规则，给出四类候选结论、待问问题和可与 RA 讨论的方案调整方向 |
| 五轴索引 | `axes` | 变更事件 / 型号配置 / 工程对象 / 受控文件 / 影响关系，五个独立可加载的索引 |
| 追问 | `grill` | 按缺口生成的优先级问题与资料清单（`grill.md`） |
| 多来源合并 | `candidates`、`merge` | 导入 Agent 候选（证据必须逐字可核），以基础包加候选投影的方式合并，冲突写入台账 |
| 阅读与查询 | `export`、`mcp` | GraphML、Neo4j CSV、Obsidian Vault；只读 MCP 服务 |
| 发布前自查 | `leakscan` | 私有禁用词表加通用敏感模式扫描 |

### 设计原则

1. **证据先于结论**：没有可核证据的候选一律拒收，不会静默保留。
2. **分层断言**：`source_assertion` / `rule_derived` / `external_corroboration` / `cross_source_candidate` / `human_adjudication`。
3. **不做多数投票**：选一个来源作基础包，其余来源作为候选投影；分歧写入冲突台账。
4. **无记录 ≠ 不存在**：计数只代表本批次、本规则的结果。
5. **主动索要经验**：缺少考纲、飞检发现、注册内容时，工具包会生成追问，而不是用通用示例假装已经有答案。

### 大文档

文件超过 50 MB、含大量图片、是 PDF 或扫描件时，会路由到 MinerU。默认优先本地部署；云端 API 需要在项目配置中明确授权上传。云端每天有 1000 页最高优先级额度，单个文件不超过 200 MB、200 页。见 [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md)。

旧版 `.doc` 建议安装 LibreOffice 转换。macOS 自带的 `textutil` 可以兜底，但会丢失或压扁部分表格。

### 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：数据契约、模块与判定边界
- [docs/AGENT-PLAYBOOK.md](docs/AGENT-PLAYBOOK.md)：Agent 操作流程与 Grill 协议
- [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md)：MinerU 本地部署与云端 API Key
- [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md)：公开发布前的脱敏与许可证检查
- [skills/ecr-graph/SKILL.md](skills/ecr-graph/SKILL.md)：可直接安装到 Agent 的技能说明

### 状态与许可证

版本 `0.1.0`，早期版本。以 [Apache License 2.0](LICENSE) 授权，另见 [NOTICE](NOTICE)。可选组件不随本仓库分发，各自适用其许可证：MinerU（MinerU Open Source License，基于 Apache 2.0 并附加条件）、LibreOffice（MPL-2.0）、pypdf（BSD-3-Clause）。
