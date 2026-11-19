---
title: ECR-Graph README
date: 2026-11-19
author: agent:Claude
type: internal
register: C
status: draft
relates: []
---

# ECR-Graph

**Evidence-governed engineering-change graphs for medical-device teams.**
ECR-Graph 是一个小型、可离线运行的工具包，面向需要处理工程更改（ECR）和受控文件的团队。客户的 Agent 可以自己安装并运行，完成以下工作：

文档解析 → 实体抽取 → 去重 → 保守消歧 → 图谱构建 → 确定性校验 → 冲突归集 → 文档关联与交叉审核 → **变更内容充分性审查** → **注册影响预评估** → 向客户追问经验与资料（Grill）

> 工具包只产出**候选**，不下结论。“合规”“放行”“不涉及注册变更”这类判断由客户的 RA、QA 和文控指定人员作出并记录。

- 只依赖 Python 标准库，支持 Python ≥ 3.9。MinerU、LibreOffice、pypdf 为可选组件。
- 每条断言都带证据定位：派生文本路径、行号、原文摘要，以及原件的 SHA-256。
- 不内置任何企业、产品或法规实例。法规经验以*客户自己的知识包*形式提供，每条都须注明来源。

## 快速开始

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
# knowledge/ 放客户经验：考纲条款、飞检发现、注册内容、软件版本规则……
python3 -m ecr_graph run -c ./my-project/ecr-graph.json
```

## 能回答什么问题

| 阶段 | 命令 | 产出 |
|---|---|---|
| 解析 | `ingest` | `work/text/*.txt` 行号化派生文本（表格行带 `[T#R#]`），`manifest.json` 记录原件哈希、解析器和告警 |
| 抽取 | `extract` | ECR、更改点（`CP-<ECR>-S01P02`）、附表文件行、文件版本、型号标签 |
| 去重/消歧 | `resolve` | 合并相同三元组的证据；`same_as` 只能来自人工裁决；仅括号限定不同的标签生成 `possible_identity` |
| 校验 | `check` | 覆盖、悬空边、原文摘要、未解析引用、版本链断点/回退/重复 |
| 关联与交叉审核 | `crossref` | 文档关联关系表（同更改点共改、同 ECR 共改、正文互引、配套规则）及缺失配套文件的发现 |
| 充分性审查 | `sufficiency` | 旧值残留、新值缺失、文件类别应含内容缺失、未声明新版本；另生成语义审查包，交给客户的 Agent |
| 注册影响预评估 | `regimpact` | 对*方案阶段*的变更逐维度比对注册内容和软件版本规则，给出四类候选结论、待问问题和可与 RA 讨论的方案调整方向 |
| 五轴索引 | `axes` | 变更事件 / 型号配置 / 工程对象 / 受控文件 / 影响关系，五个独立可加载的索引 |
| 追问 | `grill` | 按缺口生成的优先级问题与资料清单（`grill.md`） |
| 多来源合并 | `candidates`、`merge` | 导入 Agent 候选（证据必须逐字可核），以基础包加候选投影的方式合并，冲突写入台账 |
| 阅读与查询 | `export`、`mcp` | GraphML、Neo4j CSV、Obsidian Vault；只读 MCP 服务 |
| 发布前自查 | `leakscan` | 私有禁用词表加通用敏感模式扫描 |

## 设计原则

1. **证据先于结论**：没有可核证据的候选一律拒收，不会静默保留。
2. **分层断言**：`source_assertion` / `rule_derived` / `external_corroboration` / `cross_source_candidate` / `human_adjudication`。
3. **不做多数投票**：多来源合并时，选一个基础包，其余来源作为候选投影；分歧写入冲突台账。
4. **无记录 ≠ 不存在**：计数只代表本批次、本规则的结果。
5. **主动索要经验**：缺少考纲、飞检发现、注册内容时，工具包会生成追问，而不是用通用示例假装已经有答案。

## 大文档

文件超过 50 MB、含大量图片、是 PDF 或扫描件时，会路由到 MinerU。默认优先本地部署；云端 API 需要项目配置明确授权上传。见 [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md)。

旧版 `.doc` 建议安装 LibreOffice 转换。macOS 自带的 `textutil` 可以兜底，但会丢失或压扁部分表格，附表行数会明显偏少。

## 文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：数据契约、模块与判定边界
- [docs/AGENT-PLAYBOOK.md](docs/AGENT-PLAYBOOK.md)：客户 Agent 的操作流程与 Grill 协议
- [docs/LARGE-DOCUMENTS.md](docs/LARGE-DOCUMENTS.md)：MinerU 本地部署与云端 API Key
- [docs/RELEASE-CHECKLIST.md](docs/RELEASE-CHECKLIST.md)：公开发布前的脱敏与许可证检查
- [skills/ecr-graph/SKILL.md](skills/ecr-graph/SKILL.md)：可直接安装到 Agent 的技能说明

## 状态

`0.1.0`，草稿。尚未选定许可证，也尚未公开发布。发布前须完成 RELEASE-CHECKLIST 并经项目 Owner 确认。

---

*English summary.* ECR-Graph is a dependency-free Python toolkit that turns engineering change requests and controlled documents into an evidence-backed graph, then runs deterministic checks, cross-document review, change-content sufficiency review and an early registration-impact pre-assessment. Every output is a candidate for a named human reviewer; regulatory knowledge is supplied by the user, with sources.
