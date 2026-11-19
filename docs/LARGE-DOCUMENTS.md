---
title: ECR-Graph 大文档解析（MinerU）
date: 2026-11-19
author: agent:Claude
type: internal
register: C
status: draft
relates: []
---

# 大文档解析：MinerU

满足以下任一条件时，ECR-Graph 会把文件交给 MinerU 解析：

- PDF 或图片；
- 文件大于 `large_document.size_mb`（默认 50 MB）；
- 内嵌图片数超过 `large_document.images`（默认 30）。

选择顺序由 `mineru.mode` 决定：`auto`（先本地，后云端），也可以设为 `local`、`cloud` 或 `off`。

## 方案 A：本地部署（推荐，文件不出本机）

MinerU 4.x 需要 Python 3.11–3.14。工具包自身可以运行在 3.9 上，因此 MinerU 要装进独立的虚拟环境：

```bash
scripts/install_mineru.sh              # 默认安装到 ~/.ecr-graph/mineru，档位 standard
export PATH="$HOME/.ecr-graph/mineru/bin:$PATH"
python3 -m ecr_graph mineru doctor
```

官方给出的内存参考：`basic` 档在 ONNX 下约需 2 GB；`standard`/`advanced` 档在 ONNX + llama.cpp 下约需 8 GB；用 PyTorch 跑需要 16 GB，并建议配 8 GB 以上显存。首次运行会下载数 GB 的模型。

如果 CLI 用法与上面不同（例如 2.x 版的 `mineru -p … -o …`），可以在配置里写 `mineru.local_command` 模板，支持的占位符有 `{input}`、`{output}`、`{output_md}`、`{tier}`。

## 方案 B：云端 API（需要文件所有者授权）

1. 工程师在 <https://mineru.net> 注册账号，在 API 管理页面申请 API Key。
2. 只在本机 shell 中设置环境变量，**不要写进配置文件或代码仓库**：
   ```bash
   export MINERU_API_KEY="<你的 Key>"
   ```
3. 由文件所有者确认可以上传后，在项目配置里打开：
   ```json
   {"mineru": {"mode": "cloud", "cloud_upload_allowed": true}}
   ```

**额度与限制**（以下为撰写时官方文档的说法，使用前请到官网核对）：

- 每个账号每天有 **1000 页**最高优先级解析额度，超出部分降为较低优先级处理；
- 单个文件不超过 **200 MB**，不超过 **200 页**。

工具包会自动按 200 页切分页段提交，在本机 `~/.ecr-graph/mineru-quota.json` 中累计当天已提交的页数。超出 1000 页时默认停止，需要加 `--allow-low-priority` 才会继续。超过 200 MB 的文件不能直接上云，可以选择：

```bash
pip install pypdf
python3 -m ecr_graph mineru split big.pdf --out parts/   # 每 200 页切一份
```

或者改用本地 MinerU（本地没有大小限制）。

## 常见情况

| 现象 | 处理 |
|---|---|
| `.doc` 附表行数明显偏少 | macOS `textutil` 会压扁部分表格。安装 LibreOffice 后重新 `ingest` |
| manifest 提示“embedded image(s) not read” | 图片里的签名、图纸或截图没有被读取。对这些文件启用 MinerU，或人工复核 |
| 云端报每日任务数已达上限 | 次日再提交，或改用本地部署 |
