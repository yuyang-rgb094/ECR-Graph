---
title: ECR-Graph Agent 操作手册与 Grill 协议
date: 2026-11-19
author: agent:Claude
type: internal
register: C
status: draft
relates: []
---

# Agent 操作手册

本手册写给在客户环境里运行 ECR-Graph 的 Agent。

## 0. 硬规则

1. **原件只读**：不改名、不移动、不覆盖源文档。转换结果只写入 `work/`。
2. **只产候选**：不得写“合规”“可放行”“不涉及注册变更”“评审通过”。只陈述事实、矛盾和待裁决事项，并注明应由谁确认。
3. **逐字引用**：编号、数值、版本号一律原样引用并注明出处。查不到的写“文中未出现”，不要补全。
4. **不猜经验**：考纲、飞检经验、注册内容和版本规则缺失时，先运行 `grill` 向客户索要，不要用模板示例代替。
5. **上传须授权**：只有项目配置中 `mineru.cloud_upload_allowed=true` 时，才能把文件发往云端解析。这个开关由文件所有者决定，Agent 不得自行打开。

## 1. 首次接手

```bash
python3 -m ecr_graph init ./project
python3 -m ecr_graph grill -c ./project/ecr-graph.json   # 先看缺什么
```

把 `grill.md` 中优先级 P1 的问题交给客户，**每次最多 3 个**，并说明需要什么文件、什么格式。

## 2. Grill 协议

| 缺口 | 向谁索要 | 落盘位置 |
|---|---|---|
| 检查考纲 / 审核清单 | QA、RA | `knowledge/inspection_checklist.jsonl` |
| 飞检、体系核查缺陷，CAPA，经验教训 | QA | `knowledge/inspection_findings.jsonl`、`knowledge/experience/*.md` |
| 注册证范围、结构组成、产品技术要求中的指标与限值 | RA | `knowledge/registration_items.jsonl` |
| 软件版本命名规则，以及哪一位表示重大更新 | RA、软件配置管理 | `knowledge/software_version_rule.json` |
| 文件编号规则、文件类别 | 文控 | `knowledge/doc_classes.json` |
| 更改后版本文件 | 文控、研发 | `revised/` |
| 型号标签是否同一 | 产品、RA | `knowledge/aliases.json`（须写 `adjudicated_by`）或 `distinct.json` |

追问方式：

- 先说明**为什么需要**（会影响哪一项审查），再说明**交什么**，最后给模板。
- 客户口头回答也要记录：写明答复人、日期和适用范围，存为 `knowledge/experience/<日期>-<主题>.md`。
- 客户的回答和已有资料矛盾时，不自行取舍，把两边原文都列出来，请客户裁决。
- 每补一次知识，就重跑受影响的阶段，例如 `crossref`、`sufficiency`、`regimpact`。

## 3. 日常运行

```bash
python3 -m ecr_graph run -c ./project/ecr-graph.json
```

阅读顺序：`reports/summary.md` → `reports/grill.md` → `reports/crossref.json` → `reports/sufficiency.json` → `axes/05-impact-relationships.json`。

## 4. 充分性语义审查（Agent 的主要工作）

`sufficiency` 会为每个（更改点，受影响文件）生成一个审查包，写入 `reports/sufficiency_packets.jsonl`。逐个阅读审查包，按 `answer_schema` 作答，并写入 `responses.jsonl`：

```json
{"packet_id": "PKT-…", "verdict_candidate": "gaps_found", "reviewer": "agent:<名称>",
 "gaps": [{"description": "未写明新的超时阈值", "expected_content": "超时 5 s",
           "absent": true},
          {"description": "第 12 行仍是旧流程", "expected_content": "新流程",
           "evidence": [{"path": "text/…txt", "line_start": 12, "line_end": 12, "quote": "原文逐字"}]}]}
```

```bash
python3 -m ecr_graph review-ingest -c ./project/ecr-graph.json responses.jsonl
```

没有可核证据、也没有标 `absent` 的缺口会被拒收。判断不了时，答 `cannot_judge`，并在 `needs` 里写明还需要什么。

## 5. 方案阶段的注册影响预评估

工程师一提出需求或变更方案，就让他用 `proposal.json` 描述，或者直接给一段文字：

```json
{"id": "PRP-…", "title": "…", "description": "…",
 "parameters": [{"parameter": "…", "old": "…", "new": "…"}],
 "software_version": {"old": "V1.2.3", "new": "V1.3.0"},
 "affected_documents": [{"file_number": "…", "classes": ["ifu"]}]}
```

```bash
python3 -m ecr_graph regimpact -c ./project/ecr-graph.json --proposal proposal.json
```

把结果中的四类候选结论、逐维度比对、待问问题和方案调整方向交给 RA。若有 `knowledge_gaps`，先完成 Grill。调整方案时必须满足两个前提：**产品安全有效**，**版本和描述如实反映变更性质**。不得为了规避注册变更而改写版本号或措辞。

## 6. 引入其他 Agent 的抽取结果

```bash
python3 -m ecr_graph candidates -c ./project/ecr-graph.json agent_output.jsonl --producer agentA
python3 -m ecr_graph merge --base ./project/work/package --candidates ./project/work/candidates/agentA --out ./project/work/merged
```

## 7. 对外查询

```json
{"mcpServers": {"ecr-graph": {"command": "python3", "args": ["-m", "ecr_graph", "mcp", "--work", "/abs/path/work"]}}}
```

只读工具：`search_entities`、`get_entity`、`list_findings`、`list_conflicts`、`axis_lookup`、`grill_questions`。
