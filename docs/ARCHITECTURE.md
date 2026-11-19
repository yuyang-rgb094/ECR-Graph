# 架构与数据契约

## 1. 分层

```
原件（只读）──► ingest ──► 派生文本 + manifest（SHA-256、解析器、告警）
                               │
                               ▼
                 extract（规则画像 profile）──► package/
                               │                 entities / triples / transitions / change_points
       Agent 候选 ──► candidates（逐字核证）──┤
                               ▼
                 resolve ──► check ──► crossref ──► sufficiency ──► axes ──► report ──► grill
                                                                         │
                 变更方案 ──► regimpact ◄── knowledge/（客户经验，带来源）◄──┘
                               │
                               ▼
                 export（GraphML / Neo4j / Obsidian）· mcp（只读）
```

各阶段之间只通过磁盘上的 package 和 report 文件交换数据，可以单独重跑。输出目录与原件分离，原件不会被改名、移动或覆盖。

## 2. 证据契约

```json
{"source_id": "EC-2601-001", "path": "text/EC-2601-001.txt", "line_start": 7, "line_end": 7,
 "quote": "[T2R4] 更改点1：…", "section_path": "section1/point1", "source_sha256": "…", "evidence_id": "EVD-…"}
```

- `path` 指向派生文本。表格行以 `[T<表>R<行>]` 开头，嵌套表格使用点号编号。
- `quote` 必须在 `line_start..line_end` 范围内逐字出现（比较前做 NFKC 归一并去掉空白）。`check` 会逐条复核。
- 图片、签名、手写批注不在文本里，会以 `[IMG n]` 占位，并在 manifest 中告警。

## 3. 主键

| 对象 | 主键 | 说明 |
|---|---|---|
| ECR | 源文件编号（`id_patterns` 从文件名中识别） | 不重排、不自造企业编号 |
| 更改点 | `CP-<ECR>-S<节>P<点>` | 节号来自“更改内容（一）”，点号来自“更改点1：” |
| 文件 | `DOC-<文件编号>` | 同号不同名 → 候选冲突 |
| 文件版本 | `DOC-<编号>@<版本>` | 版本链：`superseded_by` |
| 型号标签 | `PRD-<归一化哈希>` | 保留原写法；身份关系只用 `possible_identity` / 人工 `same_as` |

## 4. 断言层

| 层 | 来源 | 可否由 Agent 写入 |
|---|---|---|
| `source_assertion` | 原文逐字支撑 | 否（只由确定性抽取产生） |
| `rule_derived` | 确定性规则推导 | 否 |
| `external_corroboration` | 公开登记记录等 | 否（需人工导入） |
| `cross_source_candidate` | 其他候选包、Agent | 是，且必须附可核证据 |
| `human_adjudication` | 指名人员裁决 | 只经 `knowledge/aliases.json` 等带签名的文件写入 |

`same_as` 在代码层被限制为只能出现在 `human_adjudication` 层，Agent 提交的 `same_as` 会降级为 `possible_identity`。

## 5. 判定边界

| 能力 | 确定性可做 | 需要客户 Agent | 必须人做 |
|---|---|---|---|
| 文件识别完整性 | 配套规则、方向与文件类别匹配、无文件的更改点 | 判断“不涉及”理由是否成立 | 确认评估记录 |
| 内容充分性 | 旧值残留、新值缺失、类别应含要素、版本声明 | 语义层面判断是否完整、准确 | 文件责任人确认 |
| 注册影响 | 维度命中、与注册限值的数值比对、版本规则 | 方案细节解读 | RA 作出注册判断 |
| 身份消歧 | 仅括号限定不同 → 候选 | 提供证据 | 产品或 RA 裁决 |

## 6. 规则包与知识包

- `profiles/*.json`：表单版式，包括章节、更改点、附表列名、勾选框、字形修正规则。不同企业复制一份后修改即可。
- `rulepacks/cross-review`：文件类别正则、配套规则、方向期望。
- `rulepacks/sufficiency`：新旧值对、数值单位、版本、物料码、引号术语的模式，以及各类别文件应包含的要素。
- `rulepacks/registration-impact`：注册相关维度、结论顺序、方案调整提示。**模板只是起点，不代表任何监管机构的规则。**
- `knowledge/`：客户经验。每条都必须带 `source`，否则会被 Grill 标出，不会静默使用。

## 7. 五轴

每个轴文件都包含 `metadata, indexes, records, evidence_registry, query_examples, quality`，可以单独加载。跨轴跳转通过 `relations[].target_axis + target` 完成。影响关系轴为每个更改点生成一个影响包，汇集文件、型号、验证文本、风险文本和未关闭的发现。
