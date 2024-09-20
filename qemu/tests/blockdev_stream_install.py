import logging
import random
import re
import time

from virttest import utils_misc, utils_test
from virttest.tests import unattended_install

from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevStreamVMInstallTest(BlockdevStreamNowaitTest):
    """
    Block stream test with VM installation
    """

    def _is_install_started(self, start_msg):
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
            LOG_JOB.info("Sleep some time before block-stream")
            time.sleep(random.randint(10, 120))
        else:
            self.test.fail("Failed to start VM installation")

    def _wait_installation_done(self):
        # Keep the same timeout with the default used in VT
        self._bg.join(timeout=int(self.params.get("install_timeout", 4800)))
        if self._bg.is_alive():
            self.test.fail("VM installation timed out")

    def _check_clone_vm_login(self):
        """Make sure the VM can be well accessed"""
        session = self.clone_vm.wait_for_login()
        session.close()

    def pre_test(self):
        self._install_vm_in_background()
        self.prepare_snapshot_file()

    def _clone_vm_with_snapshot_image(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()

        # Disable installation settings
        cdrom = self.main_vm.params.objects("cdroms")[0]
        self.clone_vm.params["cdroms"] = cdrom
        self.clone_vm.params["boot_once"] = "c"
        for opt in [
            "cdrom_%s" % cdrom,
            "boot_path",
            "kernel_params",
            "kernel",
            "initrd",
        ]:
            self.clone_vm.params[opt] = ""

        self.clone_vm.create()
        self.clone_vm.verify_alive()

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self._wait_installation_done()
        self._clone_vm_with_snapshot_image()
        self._check_clone_vm_login()


def run(test, params, env):
    """
     Block stream with VM installation
    test steps:
        1. Install VM on system image
        2. add a snapshot image for system image
        3. take snapshot on system image
        4. do block-stream
        5. wait till stream and installation done
        6. restart VM with the snapshot disk
        7. log into the VM
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamVMInstallTest(test, params, env)
    stream_test.run_test()
