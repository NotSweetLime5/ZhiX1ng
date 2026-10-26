"""Durable Redis Streams consumer groups with a transactional PostgreSQL outbox.

Business writes and jobs commit together. Only committed jobs are published. The
Lua marker closes the publish/SQL-commit crash window, and checks the actual entry
so a Redis restore can be repaired. Delivery is at least once; handlers must remain
idempotent. The SQL lease prevents concurrent processing of a reclaimed message.
"""

import json
import uuid

from redis.exceptions import ResponseError
from sqlalchemy import or_, select, update

from app import models as t

PUBLISH = """
local id = redis.call('GET', KEYS[2])
if id and #redis.call('XRANGE', KEYS[1], id, id) > 0 then return id end
id = redis.call('XADD', KEYS[1], '*', unpack(ARGV))
redis.call('SET', KEYS[2], id)
return id
"""
DEAD_LETTER = """
if redis.call('SET', KEYS[3], '1', 'NX') then
  redis.call('XADD', KEYS[2], '*', unpack(ARGV, 3))
end
return redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
"""


class TaskQueue:
    groups = {"stream:doc-etl": "g-docetl", "stream:eval": "g-eval", "stream:jobs": "g-jobs"}

    def __init__(self, rt, consumer=None):
        self.rt = rt
        self.consumer = consumer or "python-" + uuid.uuid4().hex
        self.cursors = dict.fromkeys(self.groups, "0-0")
        self.next_stream = 0

    def key(self, name):
        # Keep original Go stream/group names locally; isolate tests and other deployments.
        return name if self.rt.cfg.redis_namespace == "nx" else self.rt.cfg.redis_namespace + ":" + name

    def stream(self, kind):
        return "stream:doc-etl" if kind == "doc_etl" else "stream:eval" if kind == "eval" else "stream:jobs"

    async def setup(self):
        for stream, group in self.groups.items():
            try:
                await self.rt.redis.xgroup_create(self.key(stream), group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    async def recover_outbox(self):
        async with self.rt.db.engine.begin() as conn:
            await conn.execute(update(t.jobs).where(t.jobs.c.status == "pending").values(stream_id=""))
            # Recover expired workers too, including Redis loss after SQL recorded delivery.
            await conn.execute(
                update(t.jobs)
                .where(
                    t.jobs.c.status == "running",
                    or_(t.jobs.c.lease_until.is_(None), t.jobs.c.lease_until < t.now()),
                )
                .values(status="pending", lease_until=None, stream_id="")
            )

    async def publish(self):
        async with self.rt.db.engine.begin() as conn:
            rows = (
                (
                    await conn.execute(
                        select(t.jobs)
                        .where(
                            t.jobs.c.status == "pending",
                            t.jobs.c.stream_id == "",
                        )
                        .order_by(t.jobs.c.id)
                        .with_for_update(skip_locked=True)
                        .limit(100)
                    )
                )
                .mappings()
                .all()
            )
            for job in rows:
                stream = self.stream(job["kind"])
                marker = self.key(f"queue:published:{job['id']}:{job['queue_revision']}")
                fields = {
                    "job_id": str(job["id"]),
                    "revision": str(job["queue_revision"]),
                    "kind": job["kind"],
                    "payload": json.dumps(job["payload"]),
                }
                fields.update({k: str(v) for k, v in job["payload"].items() if k in {"doc_id", "run_id"}})
                args = [value for pair in fields.items() for value in pair]
                ident = await self.rt.redis.eval(PUBLISH, 2, self.key(stream), marker, *args)
                await conn.execute(update(t.jobs).where(t.jobs.c.id == job["id"]).values(stream_id=ident))
            return len(rows)

    async def receive(self):
        streams = list(self.groups.items())
        for offset in range(len(streams)):
            index = (self.next_stream + offset) % len(streams)
            stream, group = streams[index]
            result = await self.rt.redis.xautoclaim(
                self.key(stream),
                group,
                self.consumer,
                self.rt.cfg.worker_claim_idle_ms,
                self.cursors[stream],
                count=1,
            )
            self.cursors[stream] = result[0]
            if result[1]:
                ident, fields = result[1][0]
                self.next_stream = (index + 1) % len(streams)
                return stream, ident, fields
            fresh = await self.rt.redis.xreadgroup(
                group,
                self.consumer,
                {self.key(stream): ">"},
                count=1,
                block=100,
            )
            if fresh:
                ident, fields = fresh[0][1][0]
                self.next_stream = (index + 1) % len(streams)
                return stream, ident, fields
        return None

    async def heartbeat(self, delivery):
        stream, ident, _ = delivery
        await self.rt.redis.xclaim(
            self.key(stream), self.groups[stream], self.consumer, 0, [ident], justid=True
        )

    async def ack(self, delivery, error=None):
        stream, ident, fields = delivery
        if error is not None:
            values = {**fields, "error": str(error), "source_id": ident}
            args = [value for pair in values.items() for value in pair]
            await self.rt.redis.eval(
                DEAD_LETTER,
                3,
                self.key(stream),
                self.key(stream + ":dlq"),
                self.key("queue:dlq:" + stream + ":" + ident),
                self.groups[stream],
                ident,
                *args,
            )
        else:
            await self.rt.redis.xack(self.key(stream), self.groups[stream], ident)
