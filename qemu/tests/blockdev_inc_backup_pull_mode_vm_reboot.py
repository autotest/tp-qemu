import os
import re
import socket
import time

from avocado.utils import process
from virttest import utils_misc
from virttest.qemu_devices.qdevices import QBlockdevFormatNode

from provider.backup_utils import copyif
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.job_utils import query_jobs
from provider.nbd_image_export import InternalNBDExportImage


class BlockdevIncBackupPullModeRebootVMTest(BlockdevLiveBackupBaseTest):
    """Reboot VM during pulling image from client"""

    def __init__(self, test, params, env):
        super(BlockdevIncBackupPullModeRebootVMTest, self).__init__(test, params, env)

        self._job = None
        self._nbd_export = None
        localhost = socket.gethostname()
        self.params["nbd_server"] = localhost if localhost else "localhost"

        # the fleecing image to be exported
        self.params["image_name_image1"] = self.params["image_name"]
        self.params["image_format_image1"] = self.params["image_format"]
        self._fleecing_image_obj = self.source_disk_define_by_params(
            self.params, self._full_bk_images[0]
        )
        self.trash.append(self._fleecing_image_obj)

        # local target image, where data is copied from nbd image
        self._client_image_obj = self.source_disk_define_by_params(
            self.params, self.params["client_image_%s" % self._full_bk_images[0]]
        )
        self.trash.append(self._client_image_obj)
        self._target_images = [self._client_image_obj.tag]

    def add_target_data_disks(self):
        self._fleecing_image_obj.create(self.params)

        tag = self._fleecing_image_obj.tag
        devices = self.main_vm.devices.images_define_by_params(
            tag, self.params.object_params(tag), "disk"
        )
        devices.pop()  # ignore the front end device

        for dev in devices:
            if isinstance(dev, QBlockdevFormatNode):
                dev.params["backing"] = self._source_nodes[0]
            ret = self.main_vm.devices.simple_hotplug(dev, self.main_vm.monitor)
            if not ret[1]:
                self.test.fail("Failed to hotplug '%s'" % dev)

    def generate_data_file(self, tag, filename=None):
        """
        No need to create files, just start vm from the target,
        also note that, currently, creating a file may cause
        qemu core dumped due to a product bug 1879437
        """
        pass

    def remove_files_from_system_image(self, tmo=60):
        """No need to remove files for no file is created"""
        pass

    def prepare_test(self):
        super(BlockdevIncBackupPullModeRebootVMTest, self).prepare_test()
        self._nbd_export = InternalNBDExportImage(
            self.main_vm, self.params, self._full_bk_images[0]
        )
        self._nbd_export.start_nbd_server()
        self._client_image_obj.create(self.params)
        self._error_msg = "{pid} Aborted|(core dumped)".format(
            pid=self.main_vm.get_pid()
        )

    def export_full_bk_fleecing_img(self):
        self._nbd_export.add_nbd_image(self._full_bk_nodes[0])

    def do_full_backup(self):
        super(BlockdevIncBackupPullModeRebootVMTest, self).do_full_backup()
        self._job = [job["id"] for job in query_jobs(self.main_vm)][0]

    def _copy_full_data_from_export(self):
        nbd_image = self.params["nbd_image_%s" % self._full_bk_images[0]]
        copyif(self.params, nbd_image, self._client_image_obj.tag)

    def _wait_till_qemu_io_active(self):
        for i in range(self.params.get_numeric("cmd_timeout", 20) * 10):
            if process.system("ps -C qemu-io", ignore_status=True, shell=True) == 0:
                break
            time.sleep(0.1)
        else:
            self.test.error("Cannot detect the active qemu-io process")

    def _reboot_vm_during_data_copy(self):
        self._wait_till_qemu_io_active()
        self.main_vm.reboot(method="system_reset")

    def _is_qemu_aborted(self):
        log_file = os.path.join(
            self.test.resultsdir, self.params.get("debug_log_file", "debug.log")
        )
        with open(log_file, "r") as f:
            out = f.read().strip()
            return re.search(self._error_msg, out, re.M) is not None

    def pull_data_and_reboot_vm_in_parallel(self):
        """run data copy and vm reboot in parallel"""
        targets = [self._reboot_vm_during_data_copy, self._copy_full_data_from_export]
        try:
            utils_misc.parallel(targets)
        except Exception:
            if self._is_qemu_aborted():
                self.test.fail("qemu aborted(core dumped)")
            else:
                raise

    def cancel_job(self):
        self.main_vm.monitor.cmd("job-cancel", {"id": self._job})

    def check_clone_vm_login(self):
        session = self.clone_vm.wait_for_login(
            timeout=self.params.get_numeric("login_timeout", 300)
        )
        session.close()

    def do_test(self):
        self.do_full_backup()
        self.export_full_bk_fleecing_img()
        self.pull_data_and_reboot_vm_in_parallel()
        self.cancel_job()
        self.prepare_clone_vm()
        self.check_clone_vm_login()


def run(test, params, env):
    """
    Reboot VM while pulling data from fleecing image

    test steps:
        1. boot VM
        2. add fleecing disk for full backup to VM via qmp commands
        3. do full backup(sync=none) with bitmap
        4. export the full backup image by internal nbd server
        5. copy data from nbd image exported in step 4
           into an image, e.g. fullbk
        6. reboot vm while copying data
        7. boot vm with the backup image, log into vm successfully

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncBackupPullModeRebootVMTest(test, params, env)
    inc_test.run_test()
