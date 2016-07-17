import logging
import time
import random
from autotest.client.shared import error
from autotest.client.shared import utils
from qemu.tests import drive_mirror


class DriveMirrorSimple(drive_mirror.DriveMirror):

    def __init__(self, test, params, env, tag):
        super(DriveMirrorSimple, self).__init__(test, params, env, tag)

    @error.context_aware
    def query_status(self):
        """
        query running block mirroring job info;
        """
        error.context("query job status", logging.info)
        if not self.get_status():
            raise error.TestFail("No active job")

    @error.context_aware
    def readonly_target(self):
        error.context("Set readonly bit on target image", logging.info)
        cmd = "chattr +i %s" % self.target_image
        return utils.system(cmd)

    @error.context_aware
    def clear_readonly_bit(self):
        error.context("Clear readonly bit on target image", logging.info)
        cmd = "chattr -i %s" % self.target_image
        return utils.system(cmd)


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
            except Exception, detail:
                if params.get("negative_test") == "yes":
                    keywords = params.get("error_key_words", "Could not open")
                    if simple_test.get_status():
                        raise error.TestFail("Block job not cancel as expect")
                    if keywords not in str(detail):
                        raise
            simple_test.action_before_steady()
            if simple_test.get_status():
                simple_test.cancel()
    finally:
        simple_test.action_before_cleanup()
        simple_test.clean()
