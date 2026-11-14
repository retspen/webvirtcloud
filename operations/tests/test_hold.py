"""Short operations hold transient claims for their duration; a thread may
nest them; a job thread holds its job's claims."""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from operations import claims
from operations.models import Claim, Operation

S, X = Claim.SHARED, Claim.EXCLUSIVE


class HoldTestCase(TransactionTestCase):
    def test_claims_live_for_the_block(self):
        with claims.hold({"instance:u1": X}):
            self.assertTrue(Claim.objects.filter(resource="instance:u1").exists())
        self.assertFalse(Claim.objects.exists())

    def test_another_thread_is_refused_at_once(self):
        inside, release, seen = threading.Event(), threading.Event(), []

        def holder():
            try:
                with claims.hold({"instance:u1": X}):
                    inside.set()
                    release.wait(10)
            finally:
                connection.close()

        t = threading.Thread(target=holder)
        t.start()
        self.assertTrue(inside.wait(10))
        try:
            with claims.hold({"instance:u1": X}):
                pass
        except claims.Busy as busy:
            seen.append(busy.blocker)
        finally:
            release.set()
            t.join(10)
        self.assertEqual(seen, [None])

    def test_nesting_in_one_thread_reuses_held_claims(self):
        with claims.hold({"compute:1": X}):
            with claims.hold({"compute:1": S, "instance:u1": X}):
                self.assertEqual(Claim.objects.count(), 2)
            self.assertEqual(Claim.objects.count(), 1)

    def test_a_shared_claim_cannot_be_upgraded(self):
        with claims.hold({"compute:1": S}):
            with self.assertRaisesRegex(RuntimeError, "upgrade"):
                with claims.hold({"compute:1": X}):
                    pass

    def test_a_job_thread_holds_its_own_claims(self):
        user = get_user_model().objects.create_user("hold_user", "h@example.com", "pw")
        op = Operation(kind="test.noop", user=user, username="hold_user", submission_key="k",
                       resource="instance:u1", resource_label="c/vm")
        claims.admit_job(op, {"compute:1": S, "instance:u1": X}, existing=lambda: None)
        with claims.adopted(op):
            with claims.hold({"compute:1": S, "instance:u1": X}):
                pass
        with self.assertRaises(claims.Busy):
            with claims.hold({"instance:u1": X}):
                pass
