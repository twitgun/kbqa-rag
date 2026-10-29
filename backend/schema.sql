-- ============================================================
-- 知源 · 知识库问答系统  数据库建库脚本
-- MySQL 8.0.16+ (实测 8.0.45)  |  DB: kbqa  |  Charset: utf8mb4
-- 版本: 2.0（PostgreSQL 版 → MySQL 版）
-- 用法:
--   mysql -u root -p -e "CREATE DATABASE kbqa DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
--   mysql -u root -p kbqa < 04_schema.sql
-- ============================================================
-- 与 PostgreSQL 版的差异（共 6 处，均为 MySQL 能力边界所致）:
--   1. JSONB          → JSON
--   2. TIMESTAMPTZ    → DATETIME(6)（会话时区固定 +08:00，不存 tz）
--   3. 部分索引(WHERE) → 不支持，改为普通索引
--   4. gin_trgm 模糊索引 → FULLTEXT + ngram 分词器
--   5. percentile_cont → 不支持，P50/P95 改在应用层算
--   6. CHECK 约束     → 8.0.16 起才真正生效，本脚本按 8.0.45 编写
-- ============================================================

SET NAMES utf8mb4;
SET time_zone = '+08:00';
SET FOREIGN_KEY_CHECKS = 1;

-- ------------------------------------------------------------
-- 1. documents 文档表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    kb_id             INT             NOT NULL DEFAULT 1,
    title             VARCHAR(255)    NOT NULL                COMMENT '显示标题，默认取文件名去扩展名',
    original_filename VARCHAR(255)    NOT NULL                COMMENT '原始文件名，引用展示用',
    file_ext          VARCHAR(10)     NOT NULL                COMMENT '小写无点，如 md/docx/pdf',
    file_hash         CHAR(64)        NOT NULL                COMMENT 'SHA-256，去重键',
    file_path         VARCHAR(500)    NOT NULL                COMMENT '相对 data/ 的路径',
    file_size         BIGINT          NOT NULL DEFAULT 0,
    char_count        INT             NOT NULL DEFAULT 0      COMMENT '提取的纯文本字符数',
    page_count        INT             NULL                    COMMENT 'PDF 页数，其他为 NULL',
    chunk_count       INT             NOT NULL DEFAULT 0,
    status            VARCHAR(20)     NOT NULL DEFAULT 'pending'
                      COMMENT 'pending/parsing/indexing/ready/failed',
    chunk_strategy    VARCHAR(20)     NULL,
    chunk_params      JSON            NULL                    COMMENT '实际使用的切分参数',
    parsed_meta       JSON            NULL                    COMMENT '标题数/表格数/代码块数等',
    error_code        VARCHAR(20)     NULL,
    error_detail      VARCHAR(2000)   NULL,
    version           INT             NOT NULL DEFAULT 1      COMMENT '重建次数/乐观锁',
    created_at        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at        DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                      ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_documents_hash (file_hash),
    KEY idx_documents_status  (status),
    KEY idx_documents_created (created_at),
    FULLTEXT KEY ft_documents_title (title) WITH PARSER ngram,
    CONSTRAINT ck_documents_status
      CHECK (status IN ('pending','parsing','indexing','ready','failed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='知识库文档元信息';

-- ------------------------------------------------------------
-- 2. chunks 片段表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    chunk_uid      VARCHAR(40)     NOT NULL                COMMENT 'd{doc_id}_c{index:05d}，同时作 Chroma id',
    doc_id         BIGINT UNSIGNED NOT NULL,
    chunk_index    INT             NOT NULL                COMMENT '文档内序号，从 0 开始',
    `text`         MEDIUMTEXT      NOT NULL                COMMENT '片段文本，可能带【section_path】前缀',
    char_start     INT             NOT NULL                COMMENT '在 plain_text 中的起始偏移',
    char_end       INT             NOT NULL                COMMENT '结束偏移（不含）',
    page_no        INT             NULL,
    para_start     INT             NULL,
    para_end       INT             NULL,
    section_path   VARCHAR(500)    NOT NULL DEFAULT '正文'  COMMENT '标题路径，用 " > " 分隔',
    token_count    INT             NOT NULL DEFAULT 0,
    char_len       INT             NOT NULL DEFAULT 0      COMMENT '原文跨度 = char_end - char_start，不含前缀',
    chunk_strategy VARCHAR(20)     NOT NULL DEFAULT 'structure',
    created_at     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_chunks_uid (chunk_uid),
    KEY idx_chunks_doc     (doc_id, chunk_index),
    KEY idx_chunks_created (created_at),
    CONSTRAINT fk_chunks_doc FOREIGN KEY (doc_id)
      REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT ck_chunks_range CHECK (char_end > char_start),
    CONSTRAINT ck_chunks_len   CHECK (char_len = char_end - char_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='文档切分后的检索单元';

-- ------------------------------------------------------------
-- 3. index_jobs 索引任务表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS index_jobs (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    job_type     VARCHAR(20)     NOT NULL
                 COMMENT 'ingest/reindex/build_all/delete_index',
    doc_id       BIGINT UNSIGNED NULL,
    status       VARCHAR(20)     NOT NULL DEFAULT 'queued'
                 COMMENT 'queued/running/succeeded/failed/canceled',
    progress     INT             NOT NULL DEFAULT 0,
    total_steps  INT             NOT NULL DEFAULT 0,
    done_steps   INT             NOT NULL DEFAULT 0,
    message      VARCHAR(500)    NULL,
    error_code   VARCHAR(20)     NULL,
    error_detail VARCHAR(2000)   NULL,
    started_at   DATETIME(6)     NULL,
    finished_at  DATETIME(6)     NULL,
    created_at   DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_jobs_status  (status),
    KEY idx_jobs_doc     (doc_id),
    KEY idx_jobs_created (created_at),
    CONSTRAINT fk_jobs_doc FOREIGN KEY (doc_id)
      REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT ck_jobs_status
      CHECK (status IN ('queued','running','succeeded','failed','canceled')),
    CONSTRAINT ck_jobs_progress CHECK (progress BETWEEN 0 AND 100),
    CONSTRAINT ck_jobs_type
      CHECK (job_type IN ('ingest','reindex','build_all','delete_index','eval'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='异步索引任务，进程内单 worker 串行执行';

-- ------------------------------------------------------------
-- 4. sessions 会话表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sessions (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    title          VARCHAR(120)    NOT NULL DEFAULT '新会话',
    summary        VARCHAR(500)    NULL                   COMMENT '超过触发轮数后压缩的历史摘要（≤200 字）',
    message_count  INT             NOT NULL DEFAULT 0,
    turn_count     INT             NOT NULL DEFAULT 0     COMMENT '一问一答 = 1 轮',
    created_at     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    last_active_at DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_sessions_active (last_active_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='多轮对话会话';

-- ------------------------------------------------------------
-- 5. messages 消息表
--   注意: 列名用 msg_role 而非 role —— ROLE 在 MySQL 8.0 中是关键字，
--        用保留字做列名会让裸 SQL 到处翻车；API 层仍输出 "role"。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS messages (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    session_id BIGINT UNSIGNED NOT NULL,
    msg_role   VARCHAR(10)     NOT NULL                   COMMENT 'user/assistant，API 中名为 role',
    content    MEDIUMTEXT      NOT NULL,
    qa_id      BIGINT UNSIGNED NULL                       COMMENT 'assistant 消息关联问答记录',
    meta       JSON            NULL,
    created_at DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_messages_session (session_id, created_at),
    CONSTRAINT fk_messages_session FOREIGN KEY (session_id)
      REFERENCES sessions (id) ON DELETE CASCADE,
    CONSTRAINT ck_messages_role CHECK (msg_role IN ('user','assistant'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='会话消息';

-- ------------------------------------------------------------
-- 6. qa_records 问答记录表（核心）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS qa_records (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    trace_id            VARCHAR(32)   NOT NULL,
    session_id          BIGINT UNSIGNED NULL,
    message_id          BIGINT UNSIGNED NULL,
    question            TEXT          NOT NULL,
    rewritten_question  TEXT          NULL,
    answer              MEDIUMTEXT    NOT NULL,
    answer_status       VARCHAR(20)   NOT NULL DEFAULT 'ok'  COMMENT 'ok/fallback',
    fallback_reason     VARCHAR(40)   NULL
                        COMMENT 'insufficient_evidence/llm_unavailable/validation_failed/no_recall',
    citations           JSON          NULL
                        COMMENT '[{index,chunk_uid,doc_id,doc_title,page_no,char_start,char_end,quote,score}]',
    retrieved_chunks    JSON          NULL                   COMMENT 'top20 召回明细',
    retrieval_meta      JSON          NULL                   COMMENT 'max_score/tau/passed/...',
    model_insufficient  BOOLEAN       NOT NULL DEFAULT FALSE,
    confidence          DECIMAL(4,3)  NULL,
    parse_ok            BOOLEAN       NOT NULL DEFAULT FALSE,
    retry_count         INT           NOT NULL DEFAULT 0,
    llm_called          BOOLEAN       NOT NULL DEFAULT TRUE,
    llm_model           VARCHAR(40)   NULL,
    prompt_tokens       INT           NULL,
    completion_tokens   INT           NULL,
    latency_ms          INT           NOT NULL DEFAULT 0,
    latency_breakdown   JSON          NULL,
    config_snapshot     JSON          NOT NULL DEFAULT (JSON_OBJECT()),
    error_code          VARCHAR(20)   NULL,
    error_detail        VARCHAR(2000) NULL,
    raw_output          TEXT          NULL                   COMMENT '原始返回，截断 2000 字',
    mode                VARCHAR(4)    NOT NULL DEFAULT 'L4'  COMMENT 'L1/L2/L3/L4',
    created_at          DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_qa_trace (trace_id),
    KEY idx_qa_created  (created_at),
    KEY idx_qa_session  (session_id),
    KEY idx_qa_mode     (mode),
    KEY idx_qa_fallback (fallback_reason),
    CONSTRAINT ck_qa_status   CHECK (answer_status IN ('ok','fallback')),
    CONSTRAINT ck_qa_mode     CHECK (mode IN ('L1','L2','L3','L4')),
    CONSTRAINT ck_qa_fallback CHECK (fallback_reason IS NULL OR fallback_reason IN
      ('insufficient_evidence','llm_unavailable','validation_failed','no_recall'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='问答全量记录：答案、引用、召回明细、耗时、配置快照';

-- ------------------------------------------------------------
-- 7. feedbacks 反馈表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feedbacks (
    id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    qa_id       BIGINT UNSIGNED NOT NULL,
    rating      TINYINT         NOT NULL                  COMMENT '1 赞 / -1 踩',
    reason_code VARCHAR(20)     NULL
                COMMENT 'unsupported/no_answer/wrong_citation/outdated/other',
    comment     VARCHAR(500)    NULL,
    created_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at  DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_feedback_qa (qa_id),
    CONSTRAINT fk_feedback_qa FOREIGN KEY (qa_id)
      REFERENCES qa_records (id) ON DELETE CASCADE,
    CONSTRAINT ck_feedback_rating CHECK (rating IN (-1, 1)),
    CONSTRAINT ck_feedback_reason CHECK (reason_code IS NULL OR reason_code IN
      ('unsupported','no_answer','wrong_citation','outdated','other'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='答案反馈，一条问答最多一条，upsert 覆盖';

-- ------------------------------------------------------------
-- 8. eval_datasets 评测集
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_datasets (
    id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name               VARCHAR(80)     NOT NULL,
    description        VARCHAR(500)    NULL,
    question_count     INT             NOT NULL DEFAULT 0,
    answerable_count   INT             NOT NULL DEFAULT 0,
    unanswerable_count INT             NOT NULL DEFAULT 0,
    source_file        VARCHAR(255)    NULL,
    created_at         DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_dataset_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评测数据集';

-- ------------------------------------------------------------
-- 9. eval_questions 评测题
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_questions (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dataset_id     BIGINT UNSIGNED NOT NULL,
    seq            INT             NOT NULL,
    question       TEXT            NOT NULL,
    qtype          VARCHAR(20)     NOT NULL               COMMENT 'answerable/unanswerable',
    gold_answer    TEXT            NULL,
    gold_chunk_ids JSON            NULL,
    gold_doc_ids   JSON            NULL,
    difficulty     VARCHAR(10)     NULL                   COMMENT 'easy/medium/hard',
    category       VARCHAR(40)     NULL,
    notes          VARCHAR(500)    NULL,
    created_at     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_eval_question (dataset_id, seq),
    KEY idx_eval_q_dataset (dataset_id, seq),
    CONSTRAINT fk_eval_q_dataset FOREIGN KEY (dataset_id)
      REFERENCES eval_datasets (id) ON DELETE CASCADE,
    CONSTRAINT ck_eval_q_type CHECK (qtype IN ('answerable','unanswerable')),
    CONSTRAINT ck_eval_q_diff CHECK (difficulty IS NULL OR difficulty IN ('easy','medium','hard'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评测题目';

-- ------------------------------------------------------------
-- 10. eval_runs 评测批次
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_runs (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dataset_id      BIGINT UNSIGNED NOT NULL,
    name            VARCHAR(120)    NOT NULL,
    modes           JSON            NOT NULL DEFAULT (JSON_ARRAY())  COMMENT '["L1","L2","L3","L4"]',
    status          VARCHAR(20)     NOT NULL DEFAULT 'queued'
                    COMMENT 'queued/running/succeeded/failed/partial/canceled',
    total           INT             NOT NULL DEFAULT 0,
    finished        INT             NOT NULL DEFAULT 0,
    failed          INT             NOT NULL DEFAULT 0,
    config_snapshot JSON            NOT NULL DEFAULT (JSON_OBJECT()),
    judge_model     VARCHAR(40)     NOT NULL DEFAULT 'deepseek-chat',
    metrics         JSON            NULL,
    started_at      DATETIME(6)     NULL,
    finished_at     DATETIME(6)     NULL,
    created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_eval_run_status (status),
    CONSTRAINT fk_eval_run_dataset FOREIGN KEY (dataset_id)
      REFERENCES eval_datasets (id) ON DELETE CASCADE,
    CONSTRAINT ck_eval_run_status
      CHECK (status IN ('queued','running','succeeded','failed','partial','canceled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评测批次';

-- ------------------------------------------------------------
-- 11. eval_items 评测明细
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eval_items (
    id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id              BIGINT UNSIGNED NOT NULL,
    question_id         BIGINT UNSIGNED NOT NULL,
    mode                VARCHAR(4)      NOT NULL,
    answer              MEDIUMTEXT      NULL,
    citations           JSON            NULL,
    is_fallback         BOOLEAN         NOT NULL DEFAULT FALSE,
    fallback_reason     VARCHAR(40)     NULL,
    retrieved_chunk_ids JSON            NULL,
    recall5             DECIMAL(4,3)    NULL,
    mrr10               DECIMAL(4,3)    NULL,
    judge               JSON            NULL,
    human_verdict       VARCHAR(10)     NULL,
    human_note          VARCHAR(500)    NULL,
    latency_ms          INT             NULL,
    error               VARCHAR(500)    NULL,
    created_at          DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_eval_item (run_id, question_id, mode),
    KEY idx_eval_item_run (run_id, mode),
    CONSTRAINT fk_eval_item_run FOREIGN KEY (run_id)
      REFERENCES eval_runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_eval_item_q FOREIGN KEY (question_id)
      REFERENCES eval_questions (id) ON DELETE CASCADE,
    CONSTRAINT ck_eval_item_mode CHECK (mode IN ('L1','L2','L3','L4'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='评测逐题结果';

-- ------------------------------------------------------------
-- 12. app_configs 配置表
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS app_configs (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    config_key      VARCHAR(100)    NOT NULL,
    config_value    JSON            NOT NULL,
    default_value   JSON            NOT NULL,
    value_type      VARCHAR(20)     NOT NULL              COMMENT 'int/float/bool/str/enum/json',
    group_name      VARCHAR(40)     NOT NULL              COMMENT 'chunk/retrieval/generation/conversation/eval/runtime/upload',
    description     VARCHAR(500)    NOT NULL,
    min_value       DECIMAL(10,4)   NULL,
    max_value       DECIMAL(10,4)   NULL,
    enum_values     JSON            NULL,
    hot_reloadable  BOOLEAN         NOT NULL DEFAULT TRUE,
    updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                    ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uk_config_key (config_key),
    KEY idx_configs_group (group_name),
    CONSTRAINT ck_config_type CHECK (value_type IN ('int','float','bool','str','enum','json'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='系统配置（唯一配置源）';

-- ------------------------------------------------------------
-- 13. config_audits 配置审计
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS config_audits (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    config_key VARCHAR(100)    NOT NULL,
    old_value  JSON            NULL,
    new_value  JSON            NOT NULL,
    source     VARCHAR(20)     NOT NULL                   COMMENT 'ui/api/cli/seed',
    created_at DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_audit_key (config_key, created_at),
    CONSTRAINT ck_audit_source CHECK (source IN ('ui','api','cli','seed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='配置变更审计';

-- ============================================================
-- 种子数据：38 条配置项
-- ============================================================
INSERT INTO app_configs
    (config_key, config_value, default_value, value_type, group_name,
     description, min_value, max_value, enum_values, hot_reloadable)
VALUES
-- 切分
('chunk.strategy',           JSON_QUOTE('structure'), JSON_QUOTE('structure'), 'enum',  'chunk',
 '切分策略：structure=结构感知，fixed=固定窗口', NULL, NULL, JSON_ARRAY('structure','fixed'), FALSE),
('chunk.target_size',        CAST('800' AS JSON),  CAST('800' AS JSON),  'int',   'chunk',
 '目标片段字符数', 100, 4000, NULL, FALSE),
('chunk.max_size',           CAST('1500' AS JSON), CAST('1500' AS JSON), 'int',   'chunk',
 '单片段最大字符数，超过则强制切分', 200, 8000, NULL, FALSE),
('chunk.min_size',           CAST('120' AS JSON),  CAST('120' AS JSON),  'int',   'chunk',
 '单片段最小字符数，过短则并入相邻片段', 0, 1000, NULL, FALSE),
('chunk.overlap',            CAST('120' AS JSON),  CAST('120' AS JSON),  'int',   'chunk',
 '相邻片段重叠字符数', 0, 800, NULL, FALSE),
('chunk.preserve_table',     CAST('true' AS JSON), CAST('true' AS JSON), 'bool',  'chunk',
 '是否保留表格结构（转 Markdown 表格）', NULL, NULL, NULL, FALSE),

-- 检索
('retrieval.mode',           JSON_QUOTE('hybrid'), JSON_QUOTE('hybrid'), 'enum',  'retrieval',
 '召回通道：vector_only=仅向量，bm25_only=仅BM25，hybrid=混合',
 NULL, NULL, JSON_ARRAY('vector_only','bm25_only','hybrid'), TRUE),
('retrieval.rerank_enabled', CAST('true' AS JSON), CAST('true' AS JSON), 'bool',  'retrieval',
 '是否启用重排', NULL, NULL, NULL, TRUE),
('retrieval.top_k_vector',   CAST('30' AS JSON),   CAST('30' AS JSON),   'int',   'retrieval',
 '向量召回条数', 5, 100, NULL, TRUE),
('retrieval.top_k_bm25',     CAST('30' AS JSON),   CAST('30' AS JSON),   'int',   'retrieval',
 'BM25 召回条数', 5, 100, NULL, TRUE),
('retrieval.rrf_k',          CAST('60' AS JSON),   CAST('60' AS JSON),   'int',   'retrieval',
 'RRF 平滑常数', 1, 200, NULL, TRUE),
('retrieval.top_n_fusion',   CAST('20' AS JSON),   CAST('20' AS JSON),   'int',   'retrieval',
 '融合后进入重排的条数', 5, 50, NULL, TRUE),
('retrieval.top_k_rerank',   CAST('5' AS JSON),    CAST('5' AS JSON),    'int',   'retrieval',
 '重排后进入提示词的条数', 1, 10, NULL, TRUE),
('retrieval.tau',            CAST('0.70' AS JSON), CAST('0.70' AS JSON), 'float', 'retrieval',
 '证据充分性阈值，重排分数低于此值判定证据不足', 0.0, 1.0, NULL, TRUE),
('retrieval.tau_fallback_mode', CAST('0.02' AS JSON), CAST('0.02' AS JSON), 'float', 'retrieval',
 '重排不可用时的阈值（RRF 归一化分数，量纲不同于 sigmoid）', 0.0, 0.2, NULL, TRUE),
('retrieval.tau_cosine', CAST('0.50' AS JSON), CAST('0.50' AS JSON), 'float', 'retrieval',
 '无重排时用双塔余弦分数判定，量纲与 sigmoid 不同，需单独标定', 0.0, 1.0, NULL, TRUE),

-- 生成
('generation.model',         JSON_QUOTE('deepseek-chat'), JSON_QUOTE('deepseek-chat'), 'str', 'generation',
 '生成模型名称', NULL, NULL, NULL, TRUE),
('generation.temperature',   CAST('0.1' AS JSON),  CAST('0.1' AS JSON),  'float', 'generation',
 '采样温度', 0.0, 1.0, NULL, TRUE),
('generation.max_tokens',    CAST('1024' AS JSON), CAST('1024' AS JSON), 'int',   'generation',
 '最大输出 token', 128, 4096, NULL, TRUE),
('generation.timeout_s',     CAST('45' AS JSON),   CAST('45' AS JSON),   'int',   'generation',
 '单次 LLM 调用超时（秒）', 5, 180, NULL, TRUE),
('generation.max_retry',     CAST('1' AS JSON),    CAST('1' AS JSON),    'int',   'generation',
 '解析失败重试次数', 0, 3, NULL, TRUE),
('generation.max_context_tokens', CAST('6000' AS JSON), CAST('6000' AS JSON), 'int', 'generation',
 '提示词中上下文的最大 token 数', 1000, 30000, NULL, TRUE),
('generation.prompt_version', JSON_QUOTE('v1'),    JSON_QUOTE('v1'),     'str',   'generation',
 '提示词模板版本，对应 prompts/system_{version}.txt', NULL, NULL, NULL, TRUE),
('generation.verify_quote',  CAST('true' AS JSON), CAST('true' AS JSON), 'bool',  'generation',
 '是否校验引用 quote 必须逐字出自原文（规则 V-05）', NULL, NULL, NULL, TRUE),

-- 会话
('conversation.rewrite_enabled',       CAST('true' AS JSON), CAST('true' AS JSON), 'bool', 'conversation',
 '是否启用追问改写', NULL, NULL, NULL, TRUE),
('conversation.history_turns',         CAST('3' AS JSON),    CAST('3' AS JSON),    'int',  'conversation',
 '注入提示词的最近对话轮数', 0, 10, NULL, TRUE),
('conversation.summary_trigger_turns', CAST('6' AS JSON),    CAST('6' AS JSON),    'int',  'conversation',
 '触发历史摘要的轮数阈值', 2, 50, NULL, TRUE),
('conversation.summary_max_chars',     CAST('200' AS JSON),  CAST('200' AS JSON),  'int',  'conversation',
 '历史摘要最大字符数', 50, 1000, NULL, TRUE),

-- 评测
('eval.judge_model',  JSON_QUOTE('deepseek-chat'), JSON_QUOTE('deepseek-chat'), 'str',   'eval',
 '自动判定的模型', NULL, NULL, NULL, TRUE),
('eval.concurrency',  CAST('1' AS JSON),   CAST('1' AS JSON),   'int',   'eval',
 '评测并发数（GPU 串行建议 1）', 1, 5, NULL, TRUE),
('eval.sample_rate',  CAST('0.2' AS JSON), CAST('0.2' AS JSON), 'float', 'eval',
 '人工复核抽样比例', 0.0, 1.0, NULL, TRUE),

-- 运行时
('runtime.device',               JSON_QUOTE('cuda'), JSON_QUOTE('cuda'), 'enum', 'runtime',
 '推理设备', NULL, NULL, JSON_ARRAY('cuda','cpu'), FALSE),
('runtime.device_map',           JSON_QUOTE('auto'), JSON_QUOTE('auto'), 'enum', 'runtime',
 '显存分配：auto=两模型同卡，split=重排走 CPU', NULL, NULL, JSON_ARRAY('auto','split'), FALSE),
('runtime.embed_batch_size',     CAST('32' AS JSON), CAST('32' AS JSON), 'int',  'runtime',
 '向量化批大小，显存不足时调小', 1, 128, NULL, FALSE),
('runtime.max_concurrent_requests', CAST('5' AS JSON), CAST('5' AS JSON), 'int', 'runtime',
 '最大并发问答请求数', 1, 20, NULL, TRUE),
('runtime.request_queue_timeout_s', CAST('30' AS JSON), CAST('30' AS JSON), 'int', 'runtime',
 '请求排队超时（秒）', 1, 120, NULL, TRUE),
('runtime.retrieval_cache',      CAST('false' AS JSON), CAST('false' AS JSON), 'bool', 'runtime',
 '检索结果缓存，评测时必须关闭', NULL, NULL, NULL, TRUE),

-- 上传
('upload.max_size_mb', CAST('50' AS JSON), CAST('50' AS JSON), 'int', 'upload',
 '单文件最大体积（MB）', 1, 500, NULL, FALSE),
('upload.allowed_ext', JSON_ARRAY('docx','pdf','md','txt','xlsx'), JSON_ARRAY('docx','pdf','md','txt','xlsx'), 'json', 'upload',
 '允许的扩展名', NULL, NULL, NULL, FALSE)
ON DUPLICATE KEY UPDATE config_key = config_key;

-- 初始评测集占位
INSERT INTO eval_datasets (name, description)
VALUES ('fastapi-100-v1', 'FastAPI 中文文档评测集：70 道有答案 + 30 道无答案')
ON DUPLICATE KEY UPDATE name = name;

-- ============================================================
-- 校验（执行后手工跑一遍）
-- ============================================================
-- SELECT COUNT(*) FROM app_configs;              -- 期望 38
-- SELECT COUNT(*) FROM information_schema.tables
--   WHERE table_schema='kbqa' AND table_type='BASE TABLE';   -- 期望 13
