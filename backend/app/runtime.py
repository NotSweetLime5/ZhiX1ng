from contextlib import AsyncExitStack

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis

from app.agents.runtime import AgentRuntime
from app.agents.workflow import Workflow
from app.core.security import Security
from app.infrastructure.object_store import Objects
from app.infrastructure.vector_store import Vectors
from app.repositories.database import Database
from app.services.llm import Gateway
from app.services.memory import Memory
from app.services.rag import RAG
from app.services.tools import Tools


class Runtime:
    def __init__(self, cfg):
        self.cfg = cfg
        self.db = Database(cfg.database_url)
        self.redis = Redis.from_url(cfg.redis_url, decode_responses=True)
        self.security = Security(cfg, self.redis)
        self.gateway = Gateway(self.db, self.security, cfg)
        self.vectors = Vectors(cfg.milvus_uri, cfg.milvus_namespace, cfg)
        self.objects = Objects(cfg)
        self.rag = RAG(self.db, self.gateway, self.vectors, self.objects, cfg)
        self.memory = Memory(self.db, self.gateway, self.vectors)
        self.tools = Tools(self.db, self.rag, cfg)
        self.stack = AsyncExitStack()

    async def start(self):
        try:
            await self.redis.ping()
            await self.objects.setup()
            await self.vectors.setup()
            self.checkpointer = await self.stack.enter_async_context(
                AsyncPostgresSaver.from_conn_string(self.cfg.checkpoint_url)
            )
            await self.checkpointer.setup()
            self.agent = AgentRuntime(
                self.db, self.gateway, self.tools, self.rag, self.memory, self.checkpointer, self.cfg
            )
            self.workflow = Workflow(self.db, self.gateway, self.tools, self.rag, self.checkpointer)
            return self
        except BaseException:
            await self.close()
            raise

    async def close(self):
        await self.stack.aclose()
        await self.redis.aclose()
        await self.vectors.close()
        await self.db.engine.dispose()
