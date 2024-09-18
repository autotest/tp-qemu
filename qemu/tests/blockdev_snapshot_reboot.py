import logging
import random
import time

from virttest import error_context, utils_test

from provider.blockdev_snapshot_base import BlockDevSnapshotTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotRebootTest(BlockDevSnapshotTest):
    @error_context.context_aware
    def create_snapshot(self):
        error_context.context("do snaoshot during guest rebooting", LOG_JOB.info)
        bg_test = utils_test.BackgroundTest(self.vm_reset, "")
        bg_test.start()
        LOG_JOB.info("sleep random time to perform before snapshot")
        time.sleep(random.randint(0, 10))
        super(BlockdevSnapshotRebootTest, self).create_snapshot()
        if bg_test.is_alive():
            bg_test.join()

    def vm_reset(self):
        self.main_vm.reboot(method="system_reset")


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with system disk
    2) create target disk with qmp command
    3) load stress in guest
    4) do snapshot to target disk
    5) shutdown VM
    6) boot VM with target disk
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.setdefault("image_name_%s" % base_image, params["image_name"])
    params.setdefault("image_format_%s" % base_image, params["image_format"])
    snapshot_reboot = BlockdevSnapshotRebootTest(test, params, env)
    snapshot_reboot.run_test()
