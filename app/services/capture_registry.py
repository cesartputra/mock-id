"""Optional Redis routing registry; does not restore mutable liveness proof."""


class RedisCaptureRegistry:
    def __init__(self, url, gateway_id):
        import redis
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if not (
            parsed.scheme == "rediss"
            or (
                parsed.scheme == "redis"
                and parsed.hostname in ["localhost", "127.0.0.1"]
            )
        ):
            raise ValueError("Redis eksternal membutuhkan TLS.")
        self.client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=3)
        self.gateway_id = gateway_id

    def register(self, session_id, ttl):
        if not self.client.set(
            "mock-id:capture:" + session_id, self.gateway_id, nx=True, ex=ttl
        ):
            raise RuntimeError("Session owner registry collision.")

    def owner(self, session_id):
        return self.client.get("mock-id:capture:" + session_id)
