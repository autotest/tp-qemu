import random
import re
import time

from virttest import utils_misc, utils_test
from virttest.tests import unattended_install

from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitInstall(BlockDevCommitTest):
    def configure_system_disk(self, tag):
        pass


def run(test, params, env):
    """
    Block commit base Test

    1. Install guest
    2. create 4 snapshots during guest installation
    3. commit snapshot 3 to base
    4. installation can be finished after commit
    """

    def tag_for_install(vm, tag):
        if vm.serial_console:
            serial_output = vm.serial_console.get_output()
            if serial_output and re.search(tag, serial_output, re.M):
                return True
        test.log.info("vm has not started yet")
        return False

    block_test = BlockdevCommitInstall(test, params, env)
    args = (test, params, env)
    bg = utils_test.BackgroundTest(unattended_install.run, args)
    bg.start()
    if bg.is_alive():
        tag = params.get("tag_for_install_start", "Starting Login Service")
        if utils_misc.wait_for(
            lambda: tag_for_install(block_test.main_vm, tag), 240, 10, 5
        ):
            test.log.info("sleep random time before do snapshots")
            time.sleep(random.randint(10, 120))
            block_test.pre_test()
            try:
                block_test.commit_snapshots()
                try:
                    bg.join(timeout=1200)
                except Exception:
                    raise
                reboot_method = params.get("reboot_method", "system_reset")
                block_test.main_vm.reboot(method=reboot_method)
            finally:
                block_test.post_test()
        else:
            test.fail("Failed to install guest")
    else:
        test.fail("Installation failed to start")
