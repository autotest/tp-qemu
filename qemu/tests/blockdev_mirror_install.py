import logging
import random
import re
import time

from virttest import utils_misc, utils_test
from virttest.tests import unattended_install

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevMirrorVMInstallTest(BlockdevMirrorNowaitTest):
    """
    Block mirror test with VM installation
    """

    def _is_install_started(self, start_msg):
        # get_output can return None
        out = (
            self.main_vm.serial_console.get_output()
            if self.main_vm.serial_console
            else None
        )
        out = "" if out is None else out
        return bool(re.search(start_msg, out, re.M))

    def _install_vm_in_background(self):
        """Install VM in background"""
        self.main_vm = self.env.get_vm(self.params["main_vm"])
        args = (self.test, self.params, self.env)
        self._bg = utils_test.BackgroundTest(unattended_install.run, args)
        self._bg.start()

        LOG_JOB.info("Wait till '%s'", self.params["tag_for_install_start"])
        if utils_misc.wait_for(
            lambda: self._is_install_started(self.params["tag_for_install_start"]),
            int(self.params.get("timeout_for_install_start", 360)),
            10,
            5,
        ):
            LOG_JOB.info("Sleep some time before block-mirror")
            time.sleep(random.randint(10, 120))
        else:
            self.test.fail("Failed to start VM installation")

    def _wait_installation_done(self):
        # Installation on remote storage may take too much time,
        # we keep the same timeout with the default used in VT
        self._bg.join(timeout=int(self.params.get("install_timeout", 4800)))
        if self._bg.is_alive():
            self.test.fail("VM installation timed out")

    def _check_clone_vm_login(self):
        """Make sure the VM can be well accessed"""
        session = self.clone_vm.wait_for_login()
        session.close()

    def prepare_test(self):
        self._install_vm_in_background()
        self.add_target_data_disks()

    def clone_vm_with_mirrored_images(self):
        # Disable installation settings
        cdrom = self.main_vm.params.objects("cdroms")[0]
        self.main_vm.params["cdroms"] = cdrom
        self.main_vm.params["boot_once"] = "c"
        for opt in [
            "cdrom_%s" % cdrom,
            "boot_path",
            "kernel_params",
            "kernel",
            "initrd",
        ]:
            self.main_vm.params[opt] = ""

        super(BlockdevMirrorVMInstallTest, self).clone_vm_with_mirrored_images()

    def do_test(self):
        self.blockdev_mirror()
        self._wait_installation_done()
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self._check_clone_vm_login()


def run(test, params, env):
    """
     Block mirror with VM installation

    test steps:
        1. Install VM
        2. add a target disk for mirror to VM via qmp commands
        3. do block-mirror
        4. check the mirror disk is attached
        5. restart VM with the mirror disk
        6. log into VM to make sure VM can be accessed

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorVMInstallTest(test, params, env)
    mirror_test.run_test()
