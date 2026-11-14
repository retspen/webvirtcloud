"""Admission writes claims only when nothing active conflicts, all or
nothing; exclusive conflicts with any claim, shared only with exclusive."""

import subprocess
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from operations import claims
from operations.models import Claim, Operation

S, X = Claim.SHARED, Claim.EXCLUSIVE


def job(user, key="k"):
    return Operation(kind="test.noop", user=user, username=user.username, submission_key=key,
                     resource="instance:u1", resource_label="c/vm")


class AdmitTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("claims_user", "c@example.com", "pw")

    def test_shared_claims_coexist_and_exclusive_ones_do_not(self):
        claims.admit({"compute:1": S}, holder="a")
        claims.admit({"compute:1": S}, holder="b")
        with self.assertRaises(claims.Busy) as busy:
            claims.admit({"compute:1": X}, holder="c")
        self.assertEqual((busy.exception.resource, busy.exception.blocker), ("compute:1", None))

    def test_a_refusal_writes_nothing(self):
        claims.admit({"instance:u1": X}, holder="a")
        with self.assertRaises(claims.Busy):
            claims.admit({"compute:1": S, "instance:u1": X}, holder="b")
        self.assertFalse(Claim.objects.filter(resource="compute:1").exists())

    def test_a_job_and_its_claims_are_written_together(self):
        op = claims.admit_job(job(self.user), {"compute:1": S, "instance:u1": X}, existing=lambda: None)
        self.assertEqual(Operation.objects.get().pk, op.pk)
        self.assertEqual(set(Claim.objects.values_list("resource", "operation")),
                         {("compute:1", op.pk), ("instance:u1", op.pk)})
        with self.assertRaises(claims.Busy) as busy:
            claims.admit({"instance:u1": S}, holder="b")
        self.assertEqual(busy.exception.blocker.pk, op.pk)

    def test_an_existing_job_is_returned_before_conflicts_are_checked(self):
        first = claims.admit_job(job(self.user), {"instance:u1": X}, existing=lambda: None)
        again = claims.admit_job(job(self.user, key="k2"), {"instance:u1": X}, existing=lambda: first)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(Operation.objects.count(), 1)

    def test_a_refused_job_is_not_saved(self):
        claims.admit({"instance:u1": X}, holder="a")
        with self.assertRaises(claims.Busy):
            claims.admit_job(job(self.user), {"instance:u1": X}, existing=lambda: None)
        self.assertFalse(Operation.objects.exists())

    def test_an_expired_transient_claim_does_not_block(self):
        Claim.objects.create(resource="instance:u1", mode=X, holder="dead:1:1",
                             expires_at=timezone.now() - timedelta(seconds=1))
        claims.admit({"instance:u1": X}, holder="b")
        self.assertEqual(list(Claim.objects.values_list("holder", flat=True)), ["b"])

    def test_a_claim_of_a_process_that_ended_does_not_block(self):
        ended = subprocess.Popen(["true"])
        ended.wait()
        node = claims._node()
        Claim.objects.create(resource="instance:u1", mode=X, holder=f"{node}:{ended.pid}:1",
                             expires_at=timezone.now() + claims.TRANSIENT_TTL)
        claims.admit({"instance:u1": X}, holder="b")
        self.assertEqual(list(Claim.objects.values_list("holder", flat=True)), ["b"])

    def test_a_claim_of_a_running_process_or_another_installation_blocks(self):
        ended = subprocess.Popen(["true"])
        ended.wait()
        for holder in (claims.holder_id(), f"other-node:{ended.pid}:1"):
            with self.subTest(holder=holder):
                Claim.objects.create(resource="instance:u1", mode=X, holder=holder,
                                     expires_at=timezone.now() + claims.TRANSIENT_TTL)
                with self.assertRaises(claims.Busy):
                    claims.admit({"instance:u1": X}, holder="b")
                Claim.objects.all().delete()

    def test_keys_are_canonical(self):
        self.assertEqual(claims.compute_key(3), "compute:3")
        self.assertEqual(claims.instance_key("u-1"), "instance:u-1")
