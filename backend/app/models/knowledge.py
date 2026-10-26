from sqlalchemy import BigInteger, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import col, table

kbs = table(
    "knowledge_bases",
    col("name"),
    col("description", default=""),
    col("user_id", BigInteger, fk="users.id"),
    col("embedding_config_id", BigInteger, fk="model_configs.id"),
    col("chunk_size", Integer, 512),
    col("chunk_overlap", Integer, 64),
    col("parser_config", JSONB, dict),
    col("doc_count", Integer, 0),
    col("milvus_collection"),
    col("status", default="active"),
)

documents = table(
    "documents",
    col("kb_id", BigInteger, fk="knowledge_bases.id"),
    col("filename"),
    col("file_type"),
    col("object_key"),
    col("file_size", BigInteger, 0),
    col("source_url", default=""),
    col("status", default="pending"),
    col("error", default=""),
    col("chunk_count", Integer, 0),
    col("token_count", Integer, 0),
    col("enable_graph", Boolean, False),
    col("metadata", JSONB, dict),
)

chunks = table(
    "document_chunks",
    col("kb_id", BigInteger, fk="knowledge_bases.id"),
    col("document_id", BigInteger, fk="documents.id"),
    col("seq", Integer, 0),
    col("content"),
    col("token_count", Integer, 0),
    col("meta", JSONB, dict),
    col("vector_id", default=""),
    col("status", Integer, 1),
    timestamps=False,
)
