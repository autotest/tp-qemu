import logging
import time
import random

from virttest import utils_test
from virttest import error_context

from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlockdevSnapshotRebootTest(BlockDevSnapshotTest):

    @error_context.context_aware
    def create_snapshot(self):
        error_context.context("do snaoshot during guest rebooting",
                              logging.info)
        bg_test = utils_test.BackgroundTest(self.vm_reset, "")
        bg_test.start()
        logging.info("sleep random time to perform before snapshot")
        time.sleep(random.randint(0, 10))
        super(BlockdevSnapshotRebootTest, self).create_snapshot()

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
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    snapshot_reboot = BlockdevSnapshotRebootTest(test, params, env)
    snapshot_reboot.run_test()
