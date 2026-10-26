import asyncio
import logging

from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker


class Vectors:
    """Native Milvus dense + BM25 search, fused by RRF. No fake/lite fallback."""

    def __init__(self, uri, namespace="", cfg=None):
        self.uri = uri
        self.namespace = namespace
        self.cfg = cfg
        self.client = None

    def collection(self, name):
        return f"{self.namespace}_{name}" if self.namespace else name

    async def setup(self):
        self.client = await asyncio.to_thread(
            MilvusClient, uri=self.uri, db_name=self.cfg.milvus_database if self.cfg else "default"
        )

    async def ensure(self, name, dim):
        name = self.collection(name)

        def ensure_sync():
            if self.client.has_collection(name):
                fields = self.client.describe_collection(name)["fields"]
                dense = next(f for f in fields if f["name"] == "dense")
                if int(dense["params"]["dim"]) != dim:
                    raise ValueError("Embedding 维度发生变化，请新建知识库并重新索引")
                return
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.INT64, is_primary=True)
            for key in ("doc_id", "user_id", "agent_id"):
                schema.add_field(key, DataType.INT64)
            schema.add_field(
                "text",
                DataType.VARCHAR,
                max_length=65535,
                enable_analyzer=True,
                analyzer_params={"tokenizer": "jieba"},
            )
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=dim)
            schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
            schema.add_function(
                Function(
                    name="text_bm25",
                    function_type=FunctionType.BM25,
                    input_field_names=["text"],
                    output_field_names=["sparse"],
                )
            )
            indexes = self.client.prepare_index_params()
            indexes.add_index(
                field_name="dense",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            indexes.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
            self.client.create_collection(
                name, schema=schema, index_params=indexes, consistency_level="Strong"
            )

        await asyncio.to_thread(ensure_sync)

    async def upsert(self, name, records):
        if records:
            await self.ensure(name, len(records[0]["dense"]))
            await asyncio.to_thread(self.client.upsert, self.collection(name), records)

    async def search(self, name, vector, query, filter_=None, top_k=5):
        name = self.collection(name)
        if not await asyncio.to_thread(self.client.has_collection, name):
            return []
        requests = [
            AnnSearchRequest(
                data=[vector],
                anns_field="dense",
                expr=filter_,
                limit=self.cfg.rag_dense_top_k if self.cfg else 25,
                param={"metric_type": "COSINE", "params": {"ef": 64}},
            ),
            AnnSearchRequest(
                data=[query],
                anns_field="sparse",
                expr=filter_,
                limit=self.cfg.rag_sparse_top_k if self.cfg else 25,
                param={"metric_type": "BM25", "params": {}},
            ),
        ]
        try:
            result = await asyncio.to_thread(
                self.client.hybrid_search,
                collection_name=name,
                reqs=requests,
                ranker=RRFRanker(self.cfg.rag_rrf_k if self.cfg else 60),
                limit=top_k,
                output_fields=["text", "doc_id"],
                consistency_level="Strong",
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "Hybrid retrieval unavailable; trying dense search", exc_info=True
            )
            result = await asyncio.to_thread(
                self.client.search,
                collection_name=name,
                data=[vector],
                anns_field="dense",
                filter=filter_,
                limit=top_k,
                search_params={"metric_type": "COSINE", "params": {"ef": max(64, top_k)}},
                output_fields=["text", "doc_id"],
                consistency_level="Strong",
            )
        return result[0]

    async def delete(self, name, filter_):
        name = self.collection(name)
        if await asyncio.to_thread(self.client.has_collection, name):
            await asyncio.to_thread(self.client.delete, name, filter=filter_)

    async def drop(self, name):
        name = self.collection(name)
        if await asyncio.to_thread(self.client.has_collection, name):
            await asyncio.to_thread(self.client.drop_collection, name)

    async def close(self):
        if self.client:
            await asyncio.to_thread(self.client.close)
