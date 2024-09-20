from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest
from provider.job_utils import wait_until_job_status_match


class BlockdevMirrorErrorTest(BlockdevMirrorNowaitTest):
    """Block mirror with error source and target"""

    def check_mirror_job_stopped(self):
        tmo = int(self.params.get("mirror_error_stop_timeout", "300"))
        status = self.params.get("mirror_error_stop_status", "paused")
        for job_id in self._jobs:
            wait_until_job_status_match(self.main_vm, status, job_id, timeout=tmo)

    def do_test(self):
        self.blockdev_mirror()
        self.check_mirror_job_stopped()


def run(test, params, env):
    """
    Block mirror with '"on-source-error": "stop", "on-target-error": "stop"'

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. hotplug a target disk(actual size < 2G) for mirror
        5. do block-mirror with sync mode full
        6. check the mirror job is stopped

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorErrorTest(test, params, env)
    mirror_test.run_test()
