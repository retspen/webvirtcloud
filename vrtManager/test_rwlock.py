import threading
import time
import unittest
import warnings

from vrtManager.rwlock import ReadWriteLock


class TestReadWriteLock(unittest.TestCase):
    def setUp(self):
        self.lock = ReadWriteLock()

    def test_single_thread_read_lock(self):
        """Test basic read lock acquire and release in a single thread."""
        self.lock.acquireRead()
        self.lock.release()

    def test_single_thread_write_lock(self):
        """Test basic write lock acquire and release in a single thread."""
        self.lock.acquireWrite()
        self.lock.release()

    def test_nested_read_locks(self):
        """Test reentrant read locks by the same thread."""
        self.lock.acquireRead()
        self.lock.acquireRead()
        self.lock.release()
        self.lock.release()

    def test_nested_write_locks(self):
        """Test reentrant write locks by the same thread."""
        self.lock.acquireWrite()
        self.lock.acquireWrite()
        self.lock.release()
        self.lock.release()

    def test_release_unheld_lock_raises_value_error(self):
        """Releasing a lock when none is held should raise ValueError."""
        with self.assertRaises(ValueError):
            self.lock.release()

    def test_read_to_write_upgrade(self):
        """A thread holding a read lock can upgrade to a write lock."""
        self.lock.acquireRead()
        self.lock.acquireWrite(timeout=1.0)
        # Should now hold write lock with nested count
        self.lock.release()
        self.lock.release()

    def test_multiple_concurrent_readers(self):
        """Multiple threads should be able to acquire read locks simultaneously."""
        active_readers = 0
        max_concurrent_readers = 0
        state_lock = threading.Lock()
        barrier = threading.Barrier(5)

        def reader_task():
            nonlocal active_readers, max_concurrent_readers
            barrier.wait()
            self.lock.acquireRead(timeout=2.0)
            try:
                with state_lock:
                    active_readers += 1
                    if active_readers > max_concurrent_readers:
                        max_concurrent_readers = active_readers
                time.sleep(0.05)
            finally:
                with state_lock:
                    active_readers -= 1
                self.lock.release()

        threads = [threading.Thread(target=reader_task) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(max_concurrent_readers, 5)

    def test_writer_excludes_readers(self):
        """While a writer holds the lock, no reader should be able to acquire it."""
        reader_acquired = False
        reader_timed_out = False

        self.lock.acquireWrite()

        def reader_task():
            nonlocal reader_acquired, reader_timed_out
            try:
                self.lock.acquireRead(timeout=0.1)
                reader_acquired = True
                self.lock.release()
            except RuntimeError:
                reader_timed_out = True

        t = threading.Thread(target=reader_task)
        t.start()
        t.join()

        self.lock.release()
        self.assertFalse(reader_acquired)
        self.assertTrue(reader_timed_out)

    def test_readers_exclude_writer(self):
        """While readers hold the lock, a writer should be blocked until released."""
        writer_acquired = False
        writer_timed_out = False

        self.lock.acquireRead()

        def writer_task():
            nonlocal writer_acquired, writer_timed_out
            try:
                self.lock.acquireWrite(timeout=0.1)
                writer_acquired = True
                self.lock.release()
            except RuntimeError:
                writer_timed_out = True

        t = threading.Thread(target=writer_task)
        t.start()
        t.join()

        self.lock.release()
        self.assertFalse(writer_acquired)
        self.assertTrue(writer_timed_out)

    def test_writer_blocks_subsequent_readers(self):
        """Pending writers take priority and should block subsequent new readers."""
        order = []
        lock_held_event = threading.Event()
        writer_ready_event = threading.Event()

        # Step 1: Initial reader holds read lock
        self.lock.acquireRead()

        # Step 2: Writer attempts to acquire write lock and waits
        def writer_task():
            writer_ready_event.set()
            self.lock.acquireWrite(timeout=2.0)
            try:
                order.append("writer")
            finally:
                self.lock.release()

        # Step 3: New reader attempts to acquire read lock after writer is pending
        def new_reader_task():
            writer_ready_event.wait()
            # small delay to ensure writer is queued in pendingwriters
            time.sleep(0.05)
            self.lock.acquireRead(timeout=2.0)
            try:
                order.append("new_reader")
            finally:
                self.lock.release()

        w_thread = threading.Thread(target=writer_task)
        r_thread = threading.Thread(target=new_reader_task)

        w_thread.start()
        r_thread.start()

        writer_ready_event.wait()
        time.sleep(0.1)

        # Release initial reader: writer should acquire and complete before new reader
        self.lock.release()

        w_thread.join()
        r_thread.join()

        self.assertEqual(order, ["writer", "new_reader"])

    def test_no_deprecation_warnings(self):
        """Verify that lock operations do not emit DeprecationWarnings (e.g. currentThread, notifyAll)."""
        with warnings.catch_warnings(record=True) as caught_warnings:
            warnings.simplefilter("always", DeprecationWarning)
            lock = ReadWriteLock()
            lock.acquireRead()
            lock.release()
            lock.acquireWrite()
            lock.release()

            # Check for currentThread or notifyAll warnings
            deprecations = [
                str(w.message)
                for w in caught_warnings
                if issubclass(w.category, DeprecationWarning)
                and ("currentThread" in str(w.message) or "notifyAll" in str(w.message))
            ]
            self.assertEqual(
                deprecations,
                [],
                f"Found deprecation warnings: {deprecations}",
            )


if __name__ == "__main__":
    unittest.main()
