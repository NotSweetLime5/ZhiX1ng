import asyncio
import io

from minio import Minio


class Objects:
    def __init__(self, cfg):
        self.bucket = cfg.minio_bucket
        self.client = Minio(
            cfg.minio_endpoint,
            access_key=cfg.minio_access_key,
            secret_key=cfg.minio_secret_key,
            secure=cfg.minio_secure,
        )

    async def setup(self):
        if not await asyncio.to_thread(self.client.bucket_exists, self.bucket):
            await asyncio.to_thread(self.client.make_bucket, self.bucket)

    async def put(self, key, data):
        await asyncio.to_thread(self.client.put_object, self.bucket, key, io.BytesIO(data), len(data))

    async def get(self, key):
        def read():
            response = self.client.get_object(self.bucket, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(read)

    async def remove(self, key):
        await asyncio.to_thread(self.client.remove_object, self.bucket, key)
