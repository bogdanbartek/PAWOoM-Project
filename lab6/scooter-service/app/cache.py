import json
import logging

from redis import Redis
from redis.exceptions import RedisError
from redis.backoff import NoBackoff
from redis.retry import Retry

logger = logging.getLogger(__name__)


def make_redis(url: str):
    return Redis.from_url(
        url, decode_responses=True,
        socket_connect_timeout=0.3, socket_timeout=0.3,
        retry=Retry(NoBackoff(), 0),
    )


class JsonCache:
    """Optional cache: a Redis failure must not undo a database commit."""

    def __init__(self, client, prefix="lab2:demo", ttl=60, resource_name="locker"):
        if ttl <= 0:
            raise ValueError("TTL must be positive")
        self.client, self.prefix, self.ttl = client, prefix, ttl
        self.resource_name = resource_name

    def key(self, resource_id):
        return f"{self.prefix}:{self.resource_name}:{resource_id}"

    def get(self, resource_id):
        try:
            raw = self.client.get(self.key(resource_id))
            if raw is None:
                return None, "MISS"
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object")
            return value, "HIT"
        except RedisError:
            logger.warning("Cache unavailable; reading database")
            return None, "BYPASS"
        except (ValueError, TypeError):
            logger.warning("Invalid cached JSON; reading database")
            self.delete(resource_id)
            return None, "MISS"

    def put(self, resource_id, value):
        try:
            self.client.set(self.key(resource_id), json.dumps(value), ex=self.ttl)
            return True
        except RedisError:
            logger.warning("Cannot populate cache")
            return False

    def delete(self, resource_id):
        try:
            self.client.delete(self.key(resource_id))
            return True
        except RedisError:
            logger.warning("Invalidation failed; old value may survive until TTL")
            return False
