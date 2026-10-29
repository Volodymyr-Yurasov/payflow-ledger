import redis

from app.services.shield import LockState, Shield


class FlakyRedis:
    """Stands in for redis.Redis: counts calls and fails while `down` is set."""

    def __init__(self):
        self.down = False
        self.calls = 0
        self.store = {}

    def register_script(self, script):
        return lambda keys, args: self._call(lambda: self.store.pop(keys[0], None))

    def _call(self, fn):
        self.calls += 1
        if self.down:
            raise redis.ConnectionError("unreachable")
        return fn()

    def get(self, key):
        return self._call(lambda: self.store.get(key))

    def set(self, key, value, nx=False, px=None, ex=None):
        def do():
            if nx and key in self.store:
                return None
            self.store[key] = value.encode() if isinstance(value, str) else value
            return True

        return self._call(do)

    def ping(self):
        return self._call(lambda: True)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_shield():
    client, clock = FlakyRedis(), Clock()
    shield = Shield(client, done_ttl_s=60, lock_ttl_ms=1000, cooldown_s=5, clock=clock)
    return shield, client, clock


def test_done_cache_requires_matching_digest():
    shield, _, _ = make_shield()
    shield.mark_done("evt_1", "abc")
    assert shield.is_done("evt_1", "abc")
    assert not shield.is_done("evt_1", "different")
    assert not shield.is_done("evt_2", "abc")


def test_lock_is_exclusive_until_released():
    shield, _, _ = make_shield()
    first = shield.acquire("evt_1")
    assert first.state is LockState.ACQUIRED
    assert shield.acquire("evt_1").state is LockState.BUSY
    shield.release("evt_1", first)
    assert shield.acquire("evt_1").state is LockState.ACQUIRED


def test_outage_trips_the_breaker_and_skips_redis_during_cooldown():
    shield, client, clock = make_shield()
    client.down = True

    assert not shield.is_done("evt_1", "abc")  # fails open
    calls_after_failure = client.calls

    # Within the cooldown nothing touches Redis: no more slow failing calls.
    assert shield.acquire("evt_1").state is LockState.UNAVAILABLE
    shield.mark_done("evt_1", "abc")
    assert shield.status() == "unavailable"
    assert client.calls == calls_after_failure

    # After the cooldown Redis is tried again, and used once it's back.
    client.down = False
    clock.now += 6
    assert shield.status() == "ok"
    assert shield.acquire("evt_1").state is LockState.ACQUIRED


def test_disabled_shield_never_blocks():
    shield = Shield(None, done_ttl_s=60, lock_ttl_ms=1000)
    assert not shield.is_done("evt_1", "abc")
    assert shield.acquire("evt_1").state is LockState.UNAVAILABLE
    assert shield.status() == "disabled"
