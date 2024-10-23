import logging

from virttest import data_dir
from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils
from provider.blockdev_stream_base import BlockDevStreamTest
from provider.virt_storage.storage_admin import sp_admin

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevStreamBaseitself(BlockDevStreamTest):
    """Do block-stream based on itself"""

    def __init__(self, test, params, env):
        super(BlockdevStreamBaseitself, self).__init__(test, params, env)
        self._snapshot_images = self.params.objects("snapshot_images")
        self._trash = []

    def _disk_define_by_params(self, tag):
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        return sp_admin.volume_define_by_params(tag, params)

    def prepare_snapshot_file(self):
        """hotplug all snapshot images"""
        for tag in self._snapshot_images:
            disk = self._disk_define_by_params(tag)
            disk.hotplug(self.main_vm)
            self._trash.append(disk)

    def snapshot_test(self):
        """create one snapshot, create one new file"""
        self.generate_tempfile(
            self.disks_info[self.base_tag][1],
            filename="base",
            size=self.params["tempfile_size"],
        )

        self.snapshot_chain = [self.base_tag] + self._snapshot_images
        for idx in range(1, len(self.snapshot_chain)):
            backup_utils.blockdev_snapshot(
                self.main_vm,
                "drive_%s" % self.snapshot_chain[idx - 1],
                "drive_%s" % self.snapshot_chain[idx],
            )

            self.generate_tempfile(
                self.disks_info[self.base_tag][1],
                filename=self.snapshot_chain[idx],
                size=self.params["tempfile_size"],
            )

    def _remove_images(self):
        for img in self._trash:
            sp_admin.remove_volume(img)

    def post_test(self):
        try:
            if self.clone_vm.is_alive():
                self.clone_vm.destroy()
            self._remove_images()
        except Exception as e:
            LOG_JOB.warning(str(e))

    def clone_vm_with_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        snapshot_tag = self.snapshot_chain[-1]
        for base_tag in self.snapshot_chain[-2::-1]:
            snapshot_image = self.get_image_by_tag(snapshot_tag)
            snapshot_image.base_tag = base_tag
            base_image = self.get_image_by_tag(base_tag)
            snapshot_image.base_format = base_image.get_format()
            base_image_filename = base_image.image_filename
            snapshot_image.base_image_filename = base_image_filename
            snapshot_image.rebase(snapshot_image.params)
            snapshot_tag = base_tag
        self.clone_vm.create()

    def blockdev_stream(self):
        device = self.params["base_node"]
        get_stream_cmd = backup_utils.blockdev_stream_qmp_cmd
        cmd, arguments = get_stream_cmd(device, **self._stream_options)
        backup_utils.set_default_block_job_options(self.clone_vm, arguments)
        try:
            self.clone_vm.monitor.cmd(cmd, arguments)
        except QMPCmdError as e:
            error_msg = self.params.get("qmp_error_msg") % (device, device)
            if error_msg not in str(e.data):
                self.test.fail(str(e))
        else:
            self.test.fail("Can stream with base set to itself")

    def do_test(self):
        self.snapshot_test()
        self.clone_vm_with_snapshot()
        self.blockdev_stream()


def run(test, params, env):
    """
    Do stream base on itself
    test steps:
        1. boot VM with a data image
        2. add snapshot images
        3. create a file(base) on data image
        4. take snapshots(data->sn1->sn2),
           take one snapshot, create one new file(snx, x=1,2,3)
        5. restart VM with the sn2
        6. do stream base on itself
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamBaseitself(test, params, env)
    stream_test.run_test()
