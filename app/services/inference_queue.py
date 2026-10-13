"""One worker owns mutable models; bounded admission and non-cancelling timeouts."""

import asyncio
import concurrent.futures
import threading
from fastapi import HTTPException


class InferenceQueue:
    def __init__(self, capacity=4, timeout=30):
        self.pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="kyc"
        )
        self.slots = threading.BoundedSemaphore(capacity)
        self.timeout = timeout
        self.active = set()
        self.lock = threading.RLock()

    async def run(self, fn, *args, session=None, flag=None):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(
                429,
                "Antrean model penuh. Tahan posisi dan coba kembali.",
                headers={"Retry-After": "2"},
            )
        if session:
            with self.lock:
                self.active.add(session.id)

        def work():
            try:
                return fn(*args)
            finally:
                if session:
                    with self.lock:
                        self.active.discard(session.id)
                        # Normal completion keeps the session locked until the
                        # controller commits its evidence/decision.
                self.slots.release()

        try:
            future = self.pool.submit(work)
        except Exception:
            if session:
                with self.lock:
                    self.active.discard(session.id)
                if flag:
                    setattr(session, flag, False)
            self.slots.release()
            raise
        try:
            return await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(future)), timeout=self.timeout
            )
        except asyncio.TimeoutError:
            if session and flag:
                future.add_done_callback(lambda _: setattr(session, flag, False))
            raise HTTPException(
                503,
                "Model belum selesai dalam batas waktu. Tunggu sebelum mengambil ulang.",
            )

    def pending(self, session_id):
        with self.lock:
            return session_id in self.active

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=False)
