"""A kind for process tests: run waits for files, so the parent can kill the
worker at a chosen point. Directory from params["dir"]."""

import os
import time

from operations.jobs import Kind, Outcome, Plan, register
from operations.models import Claim, Operation


def _wait(path, seconds=30):
    end = time.monotonic() + seconds
    while not os.path.exists(path) and time.monotonic() < end:
        time.sleep(0.05)


@register
class FileStepsKind(Kind):
    name = "test.filesteps"
    label = "File steps"

    def normalize(self, raw):
        return {"dir": str(raw["dir"]), "uuid": str(raw.get("uuid", "p1"))}

    def plan(self, user, params):
        key = "instance:" + params["uuid"]
        return Plan(claims={key: Claim.EXCLUSIVE}, resource=key, label="c/vm")

    def run(self, op, ctx):
        d = op.params["dir"]
        open(os.path.join(d, "started"), "w").close()
        _wait(os.path.join(d, "go-intent"))
        ctx.record_intent(step="effect")
        open(os.path.join(d, "effect"), "w").close()  # stands for the libvirt effect
        _wait(os.path.join(d, "go-finish"))
        return {"ok": True}

    def reconcile(self, op):
        effect = os.path.exists(os.path.join(op.params["dir"], "effect"))
        return Outcome(Operation.SUCCEEDED if effect else Operation.FAILED)
