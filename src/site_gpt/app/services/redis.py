import json

import redis.asyncio as redis

from site_gpt.app.core.config import REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB


redis_client = redis.Redis(
    host=REDIS_HOST,
    port=int(REDIS_PORT),
    password=REDIS_PASSWORD,
    db=int(REDIS_DB),
    decode_responses=True,
)


async def enqueue_job(data: dict):
    await redis_client.lpush("queue:jobs", json.dumps(data))  # type: ignore
