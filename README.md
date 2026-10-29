# 知源 · 知识库问答系统

一个本地部署的知识库问答系统：把文档导入后，用自然语言提问，系统检索相关片段并**只依据这些片段**生成答案，同时给出可核对的原文引用。

- **后端**：FastAPI + SQLAlchemy + MySQL 8
- **检索**：BGE-M3 向量召回 + BM25 关键词召回 → RRF 融合
- **生成**：DeepSeek（OpenAI 兼容接口），结构化 JSON 输出
- **前端**：Vue 3 + Element Plus
- **校验**：引用必须来自本轮召回片段，且引文必须能在原文中逐字找到

## 功能

| 模块 | 说明 |
|---|---|
| 文档管理 | 上传 md / docx / pdf / txt / xlsx，异步解析与索引，支持重建与删除 |
| 检索 | 向量 + BM25 双路召回，RRF 融合，可调阈值；带检索调试接口，能看到每路分数 |
| 问答 | 多轮对话、追问改写、引用展示、证据不足时明确拒答而不是硬答 |
| 日志 | 每次问答落库，含召回明细、阈值判定、耗时分解、配置快照 |
| 配置 | 参数在线修改并即时生效，越界值拒绝，改动留审计 |
| 评测 | 数据集导入、批量跑、指标计算与报告导出 |

## 快速开始

```bash
pip install -r backend/requirements.txt

cp .env.example .env    # Windows: copy .env.example .env
# 填入 DATABASE_URL 与 DEEPSEEK_API_KEY

mysql -u root -p < backend/schema.sql

# 向量模型（约 2.3GB）放到 runtime/models/bge-m3
python scripts/fetch_model.py --repo BAAI/bge-m3

python scripts/batch_import.py       # 导入 data/corpus 下的文档
python scripts/start_backend.py      # 启动，默认 8000 端口
```

打开 http://127.0.0.1:8000 ，接口文档在 `/api/docs`。

前端开发：

```bash
cd frontend
pnpm install
pnpm dev      # 5173，代理到 8000
```

## 目录

```
backend/kbqa/
  api/          路由、依赖注入、错误码与响应封装
  core/
    ingest/     五种格式的解析器
    chunking/   结构感知切分 + 定长切分
    retrieval/  向量/BM25 召回、RRF 融合、阈值判定
    generation/ 提示词组装、模型调用、结构化输出解析
    validation/ 引用与格式校验
    fallback/   三类降级话术
  infra/        数据库、向量库、BM25、模型、任务队列
  services/     导入、问答、评测等服务层

frontend/src/
  views/        问答 / 知识库 / 日志 / 配置 / 评测台 / 系统状态
  api.js        接口封装

data/corpus/    示例语料（FastAPI 中文文档 80 篇）
scripts/        语料抓取、索引重建、批量导入、演示自检
```

## 设计要点

**证据不足时拒答，而不是让模型硬答。** 检索最高分低于阈值时直接返回兜底话术，不调用大模型——省时也避免编造。

**引用必须可核对。** 答案里的 `[1]` 对应 citations 中的条目，而 citations 的 `quote` 必须能在对应片段原文中逐字找到，否则该答案被判无效。

**结构化输出 + 重试。** 模型必须返回固定字段的 JSON；解析或校验失败会带着错误说明重试一次，仍失败则降级。

## 可观测性

- 每次问答记录 `trace_id`、召回候选与分数、阈值、耗时分解、配置快照
- `/api/v1/system/health` 检查数据库、索引、模型、API Key、磁盘
- `scripts/demo_check.py` 一键跑通"上传→索引→提问→拒答"完整路径

## 说明

- `.env` 与模型权重不入库，需自行准备
- `data/corpus/` 内容来自 FastAPI 官方中文文档（MIT 许可），仅作示例语料
- 本项目为单用户本地部署场景，未做多租户与鉴权
