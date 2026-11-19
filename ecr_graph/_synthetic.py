"""Fully fictional demo data.

Company, products, document numbers, ECR numbers, parameters and the
"regulatory" knowledge below are invented for testing. They do not describe
any real organisation, device or regulation.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import List, Sequence, Union
from xml.sax.saxutils import escape

CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                 '<Default Extension="xml" ContentType="application/xml"/>'
                 '<Override PartName="/word/document.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>')
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

Block = Union[str, List[Sequence[str]]]


def _run(text: str) -> str:
    """Render ■/□ as Wingdings symbols, like legacy Word forms do."""
    out = []
    buf = ""
    for ch in text:
        if ch in "■□":
            if buf:
                out.append(f'<w:r><w:t xml:space="preserve">{escape(buf)}</w:t></w:r>')
                buf = ""
            code = "F0FE" if ch == "■" else "F0A8"
            out.append(f'<w:r><w:sym w:font="Wingdings" w:char="{code}"/></w:r>')
        else:
            buf += ch
    if buf:
        out.append(f'<w:r><w:t xml:space="preserve">{escape(buf)}</w:t></w:r>')
    return "".join(out)


def _p(text: str) -> str:
    return f"<w:p>{_run(text)}</w:p>"


def write_docx(path: Path, blocks: List[Block]) -> Path:
    body = []
    for b in blocks:
        if isinstance(b, str):
            body.append(_p(b))
        else:
            rows = "".join("<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in row) + "</w:tr>" for row in b)
            body.append(f"<w:tbl>{rows}</w:tbl>")
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W}><w:body>{"".join(body)}</w:body></w:document>'
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", doc)
    return path


HEADER = ["序号", "适用型号", "文件编号", "文件名称", "原版本", "新版本", "处理方式"]

ECR1 = [
    "工程更改申请单（示例，虚构）",
    [["申请单号", "EC-2601-001"], ["申请日期", "2026.01.10"]],
    [["更改内容（一）"],
     ["类型：□紧急 ■常规", "产品所处阶段：□试产 ■量产"],
     ["更改性质：□工艺要求 ■设计优化 □文件错误 □法规及注册要求"],
     ["更改点1：缩短图像重建时间 问题描述：图像重建耗时较长。 原因分析：重建算法存在冗余计算。 "
      "解决方案：软件方向：将重建时间由 8 s 改为 5 s，软件版本由V2.1.3升级为V2.2.0。 结构方向：不涉及。 "
      "验证建议：进行重建时间测试。 风险评估：性能相关危害，风险可接受。"],
     ["更改点2：更换显示器支架 问题描述：支架长期使用后易松动。 原因分析：材料刚度不足。 "
      "解决方案：结构方向：支架材料由ABS改为铝合金，物料编码 4300011122334。 验证建议：进行振动试验。"],
     ["更改内容（二）"],
     ["更改性质：□设计优化 ■法规及注册要求"],
     ["更改点1：更新说明书警示语 问题描述：说明书缺少强磁场警示。 "
      "解决方案：说明书中增加“禁止在强磁场环境下使用”警示语。 验证建议：不涉及测试。"]],
    [HEADER,
     ["1", "LumaScan 100、LumaScan 100（EU）", "QD-SW-010", "软件版本配置索引", "V5.0", "V6.0", "更改内容（一）更改点1，升版"],
     ["2", "LumaScan 100", "QD-SRS-011", "软件需求规格说明", "V3.0", "V4.0", "更改内容（一）更改点1，升版"],
     ["3", "LumaScan 100", "QD-DWG-120", "显示器支架图纸", "V1.0", "V2.0", "更改内容（一）更改点2，升版"],
     ["4", "LumaScan 100", "QD-IFU-002", "产品使用说明书", "V2.0", "V3.0", "更改内容（二）更改点1，升版"],
     ["5", "LumaScan 100", "QD-TR-001", "产品技术要求", "V1.0", "V1.0", "更改内容（一）更改点3，升版"]],
]

ECR2 = [
    "工程更改申请单（示例，虚构）",
    [["申请单号", "EC-2602-004"], ["申请日期", "2026.02.20"]],
    [["更改内容（一）"],
     ["更改性质：■用户需求"],
     ["更改点1：新增测量导出功能 问题描述：用户需要导出测量结果。 解决方案：软件方向：新增CSV导出功能，"
      "软件版本由V2.2.0升级为V3.0.0。 验证建议：进行导出功能测试。"]],
    [HEADER,
     ["1", "LumaScan 100（US）", "QD-SW-010", "软件版本配置索引", "V6.0", "V7.0", "更改内容（一）更改点1，升版"],
     ["2", "LumaScan 100（US）", "QD-SRS-011", "软件需求规格说明", "V5.0", "V6.0", "更改内容（一）更改点1，升版"],
     ["3", "LumaScan 100（US）", "QD-STP-012", "软件测试报告", "/", "V1.0", "更改内容（一）更改点1，新增"]],
]

REVISED = {
    "QD-SW-010 软件版本配置索引 V6.0.txt": [
        "软件版本配置索引 QD-SW-010 V6.0（示例，虚构）",
        "修订记录：V6.0 依据 EC-2601-001 更新。",
        "发布软件版本：V2.1.3",
        "适用型号：LumaScan 100、LumaScan 100（EU）",
    ],
    "QD-SRS-011 软件需求规格说明 V4.0.txt": [
        "软件需求规格说明 QD-SRS-011 V4.0（示例，虚构）",
        "SRS-PERF-03 图像重建时间不大于 5 s。",
        "软件版本：V2.2.0",
    ],
    "QD-IFU-002 产品使用说明书 V3.0.txt": [
        "产品使用说明书 QD-IFU-002 V3.0（示例，虚构）",
        "第5章 注意事项：请勿在潮湿环境中使用。",
    ],
}

KNOWLEDGE = {
    "registration_items.jsonl": [
        {"id": "RI-001", "item": "图像重建时间", "parameter": "重建时间", "limit": "≤10 s", "unit": "s",
         "doc_class": "technical_requirements", "keywords": ["重建时间"], "source": "示例注册资料（虚构）第2.1条"},
        {"id": "RI-002", "item": "轴向分辨率", "parameter": "分辨率", "limit": "≤20 μm", "unit": "μm",
         "doc_class": "technical_requirements", "keywords": ["分辨率"], "source": "示例注册资料（虚构）第2.2条"},
    ],
    "inspection_findings.jsonl": [
        {"id": "IF-001", "finding": "设计更改未评估对说明书警示内容的影响", "clause_ref": "CL-001", "doc_classes": ["ifu"],
         "keywords": ["说明书", "警示"], "lesson": "说明书变更需同步评估标签和风险管理文件", "source": "示例检查报告（虚构）"},
    ],
    "inspection_checklist.jsonl": [
        {"id": "CL-001", "clause": "设计和开发更改应评估对产品组成部分和已交付产品的影响（示例条款）", "doc_classes": ["risk_management"],
         "keywords": ["更改", "软件"], "source": "示例检查清单（虚构）"},
    ],
}
SOFTWARE_RULE = {"pattern": r"V(\d+)\.(\d+)\.(\d+)", "components": ["major", "minor", "patch"],
                 "registration_relevant": ["major"], "source": "示例软件版本命名规则（虚构）"}
PROPOSALS = {
    "PRP-001.json": {"id": "PRP-001", "title": "放宽重建时间以支持更高采样",
                     "description": "为提升图像质量，计划将重建时间调整为 12 s，属于性能指标调整。",
                     "parameters": [{"parameter": "重建时间", "old": "5 s", "new": "12 s"}]},
    "PRP-002.json": {"id": "PRP-002", "title": "修复导出界面缺陷",
                     "description": "修复CSV导出界面显示缺陷，软件维护更新。",
                     "software_version": {"old": "V3.0.0", "new": "V3.0.1"}},
}


def write_demo(root: Path) -> str:
    root = Path(root)
    write_docx(root / "sources" / "EC-2601-001 工程更改申请单.docx", ECR1)
    write_docx(root / "sources" / "EC-2602-004 工程更改申请单.docx", ECR2)
    for name, lines in REVISED.items():
        (root / "revised").mkdir(parents=True, exist_ok=True)
        (root / "revised" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    k = root / "knowledge"
    k.mkdir(parents=True, exist_ok=True)
    for name, rows in KNOWLEDGE.items():
        (k / name).write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (k / "software_version_rule.json").write_text(json.dumps(SOFTWARE_RULE, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, p in PROPOSALS.items():
        (root / "proposals").mkdir(exist_ok=True)
        (root / "proposals" / name).write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = {"project_name": "lumascan-demo", "sources": ["sources"], "revised_documents": ["revised"],
           "work_dir": "work", "knowledge_dir": "knowledge", "mineru": {"mode": "off"}}
    (root / "ecr-graph.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"demo written to {root}; next: python3 -m ecr_graph run -c {root / 'ecr-graph.json'}"
