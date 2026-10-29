"""13 张表的 ORM 映射，字段与 02_系统设计/04_schema.sql 严格一致。

注意两处 MySQL 适配（见 ADR-004）：
  - messages 列名为 msg_role（ROLE 是 MySQL 关键字），API 层仍输出 role
  - chunks 的 text 列需引号，ORM 用属性 text 映射列 "text"
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kbqa.infra.db.session import Base

BigIntPK = BigInteger().with_variant(Integer, "sqlite")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_ext: Mapped[str] = mapped_column(String(10))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    file_path: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    chunk_strategy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chunk_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parsed_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), server_default=func.now(), onupdate=func.now()
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chunk_uid: Mapped[str] = mapped_column(String(40), unique=True)
    doc_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column("text", Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    para_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    para_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[str] = mapped_column(String(500), default="正文")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    char_len: Mapped[int] = mapped_column(Integer, default=0)
    chunk_strategy: Mapped[str] = mapped_column(String(20), default="structure")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")


class IndexJob(Base):
    __tablename__ = "index_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(20))
    doc_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    done_steps: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(120), default="新会话")
    summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sessions.id", ondelete="CASCADE")
    )
    msg_role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    qa_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())

    session: Mapped[Session] = relationship(back_populates="messages")


class QaRecord(Base):
    __tablename__ = "qa_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(32), unique=True)
    session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    question: Mapped[str] = mapped_column(Text)
    rewritten_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str] = mapped_column(Text)
    answer_status: Mapped[str] = mapped_column(String(20), default="ok")
    fallback_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieved_chunks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    retrieval_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_insufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    parse_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_called: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_model: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    latency_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(4), default="L4")
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    qa_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("qa_records.id", ondelete="CASCADE"), unique=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), server_default=func.now(), onupdate=func.now()
    )


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    answerable_count: Mapped[int] = mapped_column(Integer, default=0)
    unanswerable_count: Mapped[int] = mapped_column(Integer, default=0)
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class EvalQuestion(Base):
    __tablename__ = "eval_questions"
    __table_args__ = (UniqueConstraint("dataset_id", "seq", name="uk_eval_question"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_datasets.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    qtype: Mapped[str] = mapped_column(String(20))
    gold_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    gold_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    gold_doc_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(10), nullable=True)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_datasets.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    modes: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    total: Mapped[int] = mapped_column(Integer, default=0)
    finished: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    config_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    judge_model: Mapped[str] = mapped_column(String(40), default="deepseek-chat")
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(6), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class EvalItem(Base):
    __tablename__ = "eval_items"
    __table_args__ = (
        UniqueConstraint("run_id", "question_id", "mode", name="uk_eval_item"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_runs.id", ondelete="CASCADE")
    )
    question_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("eval_questions.id", ondelete="CASCADE")
    )
    mode: Mapped[str] = mapped_column(String(4))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    recall5: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    mrr10: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    judge: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    human_verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    human_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())


class AppConfig(Base):
    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(100), unique=True)
    config_value: Mapped[dict | list | str | int | float | bool] = mapped_column(JSON)
    default_value: Mapped[dict | list | str | int | float | bool] = mapped_column(JSON)
    value_type: Mapped[str] = mapped_column(String(20))
    group_name: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(500))
    min_value: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_value: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    enum_values: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hot_reloadable: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(6), server_default=func.now(), onupdate=func.now()
    )


class ConfigAudit(Base):
    __tablename__ = "config_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON, nullable=True
    )
    new_value: Mapped[dict | list | str | int | float | bool] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(6), server_default=func.now())
