"""
Redis Streams consumer — reads from eldercare:events and writes to SQLite.

Usage:
    python pipeline/consumer.py

Runs continuously. Safe to restart — Redis Streams tracks the last-read
message ID per consumer group, so no events are lost or double-processed.
"""
import time
import redis
from contracts.events import STREAM, StateEvent
from pipeline.store import init_db, insert_event

REDIS_HOST    = "localhost"
REDIS_PORT    = 6379
GROUP         = "pipeline"
CONSUMER      = "consumer-1"
BLOCK_MS      = 2000   # block on XREADGROUP for up to 2s before looping
HEARTBEAT_S   = 30     # log a heartbeat every N seconds so Sentry can detect silence


def get_or_create_group(r: redis.Redis) -> None:
    try:
        r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise


def run(db_path: str = "pipeline/constant.db") -> None:
    init_db(db_path)
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    get_or_create_group(r)

    print(f"Consumer started — reading {STREAM}")
    last_heartbeat = time.time()

    while True:
        results = r.xreadgroup(
            groupname=GROUP,
            consumername=CONSUMER,
            streams={STREAM: ">"},
            count=10,
            block=BLOCK_MS,
        )

        if results:
            for _, messages in results:
                for msg_id, fields in messages:
                    try:
                        event = StateEvent.from_redis(fields)
                        insert_event(event, db_path)
                        r.xack(STREAM, GROUP, msg_id)
                    except Exception as e:
                        print(f"Failed to process {msg_id}: {e}")

        now = time.time()
        if now - last_heartbeat >= HEARTBEAT_S:
            print(f"[heartbeat] consumer alive, stream={STREAM}")
            last_heartbeat = now


if __name__ == "__main__":
    run()
