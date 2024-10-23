import logging
import random
import time

from avocado.utils import process
from virttest import error_context

from qemu.tests import drive_mirror

LOG_JOB = logging.getLogger("avocado.test")


class DriveMirrorSimple(drive_mirror.DriveMirror):
    def __init__(self, test, params, env, tag):
        super(DriveMirrorSimple, self).__init__(test, params, env, tag)

    @error_context.context_aware
    def query_status(self):
        """
        query running block mirroring job info;
        """
        error_context.context("query job status", LOG_JOB.info)
        if not self.get_status():
            self.test.fail("No active job")

    @error_context.context_aware
    def readonly_target(self):
        error_context.context("Set readonly bit on target image", LOG_JOB.info)
        cmd = "chattr +i %s" % self.target_image
        return process.system(cmd)

    @error_context.context_aware
    def clear_readonly_bit(self):
        error_context.context("Clear readonly bit on target image", LOG_JOB.info)
        cmd = "chattr -i %s" % self.target_image
        return process.system(cmd)


def run(test, params, env):
    """
    drive_mirror_simple test:
    1). launch block mirroring job w/o max speed
    2). query job status on the device before steady status(optinal)
    3). reset max job speed before steady status(optional)
    4). cancel active job on the device before steady status(optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    repeats = int(params.get("repeat_times", 3))
    simple_test = DriveMirrorSimple(test, params, env, tag)
    try:
        for i in range(repeats):
            v_max, v_min = int(params.get("login_timeout", 360)) / 4, 0
            time.sleep(random.randint(v_min, v_max))
            simple_test.action_before_start()
            try:
                simple_test.start()
            except Exception as detail:
                if params.get("negative_test") == "yes":
                    keywords = params.get("error_key_words", "Could not open")
                    if simple_test.get_status():
                        test.fail("Block job not cancel as expect")
                    if keywords not in str(detail):
                        raise
            simple_test.action_before_steady()
            if simple_test.get_status():
                simple_test.cancel()
    finally:
        simple_test.action_before_cleanup()
        simple_test.clean()
