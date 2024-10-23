import random
import re
import time

from virttest import utils_misc, utils_test
from virttest.tests import unattended_install

from provider.blockdev_snapshot_base import BlockDevSnapshotTest


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) Install guest
    2) Do snapshot during guest
    3) Rebase snapshot to base after installation finished
    4) Start guest with snapshot
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def tag_for_install(vm, tag):
        if vm.serial_console:
            serial_output = vm.serial_console.get_output()
            if serial_output and re.search(tag, serial_output, re.M):
                return True
        test.log.info("VM has not started yet")
        return False

    base_image = params.get("images", "image1").split()[0]
    params.update({"image_format_%s" % base_image: params["image_format"]})
    snapshot_test = BlockDevSnapshotTest(test, params, env)
    args = (test, params, env)
    bg = utils_test.BackgroundTest(unattended_install.run, args)
    bg.start()
    if bg.is_alive():
        tag = params["tag_for_install_start"]
        if utils_misc.wait_for(
            lambda: tag_for_install(snapshot_test.main_vm, tag), 120, 10, 5
        ):
            test.log.info("sleep random time before do snapshots")
            time.sleep(random.randint(120, 600))
            snapshot_test.pre_test()
            try:
                snapshot_test.create_snapshot()
                try:
                    bg.join(timeout=1200)
                except Exception:
                    raise
                snapshot_test.verify_snapshot()
                snapshot_test.clone_vm.wait_for_login()
            finally:
                snapshot_test.post_test()
        else:
            test.fail("Failed to install guest")
    else:
        test.fail("Background process:installation not started")
