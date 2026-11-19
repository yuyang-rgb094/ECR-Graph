---
name: ecr-graph
description: Build an evidence-backed graph from engineering change requests (ECR) and controlled documents, then run cross-document review, change-content sufficiency review, registration-impact pre-assessment and customer grilling. Use when the user asks to analyse ECRs, check whether changed documents fully reflect a change, find missing companion documents, or assess whether a proposed change may affect device registration.
title: ECR-Graph 技能
type: internal
status: draft
---

# ECR-Graph skill

## When to use

- 用户给出一批 ECR / 工程更改申请单，以及受影响的文件，希望梳理变更关系、交叉审核、查找遗漏和冲突。
- 用户想知道“文件都改了，内容改够了没有”。
- 工程师提出变更方案，想在动手之前判断方案能不能做、会不会触发注册变更。

## Steps

1. 确认工具包可用：`python3 -m ecr_graph --version`。如不可用，在工具包根目录执行 `pip install -e .`，或者直接在根目录运行。
2. `python3 -m ecr_graph init <project>`，请用户把 ECR 放进 `sources/`，更改后版本放进 `revised/`。
3. **先跑 Grill**：`python3 -m ecr_graph grill -c <project>/ecr-graph.json`。按优先级每次最多问 3 个问题，向用户索要考纲、飞检经验、注册内容和版本规则。每条资料都写明来源后存入 `knowledge/`。
4. 遇到大文件、扫描件或 PDF：先运行 `mineru doctor`。优先本地部署（`scripts/install_mineru.sh`）；需要云端时，告诉用户去 mineru.net 注册 API Key，每天 1000 页为最高优先级额度，单个文件不超过 200 MB、200 页。上传前必须取得文件所有者同意。
5. `python3 -m ecr_graph run -c <project>/ecr-graph.json`，然后阅读 `reports/summary.md`。
6. 处理 `reports/sufficiency_packets.jsonl`：逐包作答，再执行 `review-ingest`。
7. 方案阶段运行 `regimpact --proposal <file>`，把结果交给 RA。
8. 向用户汇报：发现了哪些事实和矛盾、每项应由谁确认，以及还缺什么资料。

## Never

- 不改动原件，不自行打开云端上传。
- 不写“合规”“不涉及注册变更”“评审通过”这类结论。
- 不用模板里的示例规则代替客户自己的经验。
- 不把型号标签自行合并为同一对象。
