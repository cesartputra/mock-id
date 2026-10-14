"""Backpressure preserves mutable-model ownership after a response timeout."""

import asyncio
import threading
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.services.inference_queue import InferenceQueue


def test_timeout_keeps_worker_and_session_reserved_until_it_finishes():
    queue = InferenceQueue(capacity=1, timeout=0.02)
    release = threading.Event()
    session = SimpleNamespace(id="timeout-fixture", processing=True)

    def work():
        release.wait(2)
        return "done"

    async def exercise():
        with pytest.raises(HTTPException) as error:
            await queue.run(work, session=session, flag="processing")
        assert (
            error.value.status_code == 503
            and session.processing
            and queue.pending(session.id)
        )
        with pytest.raises(HTTPException) as busy:
            await queue.run(lambda: None)
        assert busy.value.status_code == 429
        release.set()
        for _ in range(50):
            if not queue.pending(session.id):
                break
            await asyncio.sleep(0.01)
        assert not session.processing
        assert await queue.run(lambda: "next") == "next"

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        queue.close()


def test_success_keeps_capture_locked_until_controller_commits():
    queue = InferenceQueue()
    session = SimpleNamespace(id="success-fixture", processing=True)
    try:
        assert (
            asyncio.run(queue.run(lambda: 123, session=session, flag="processing"))
            == 123
        )
        assert session.processing and not queue.pending(session.id)
    finally:
        queue.close()


def test_cancelled_request_keeps_native_work_reserved_then_unlocks_session():
    queue = InferenceQueue(capacity=1)
    entered, release = threading.Event(), threading.Event()
    session = SimpleNamespace(id='cancel-fixture', processing=True)

    def work():
        entered.set()
        release.wait(2)

    async def exercise():
        task = asyncio.create_task(queue.run(work, session=session, flag='processing'))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert session.processing and queue.pending(session.id)
        with pytest.raises(HTTPException) as busy:
            await queue.run(lambda: None)
        assert busy.value.status_code == 429
        release.set()
        for _ in range(50):
            if not session.processing:
                break
            await asyncio.sleep(.01)
        assert not session.processing and not queue.pending(session.id)
        assert await queue.run(lambda: 'next') == 'next'

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        queue.close()
