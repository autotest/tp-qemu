import json

from virttest import utils_misc, utils_qemu
from virttest.utils_version import VersionInterval

from provider import block_dirty_bitmap as bitmap_handle
from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlkIncModifyBackingBitmaps(BlockDevSnapshotTest):
    def reopen_backing_image(self, node_name):
        opts = []
        fmt_node = self.main_vm.devices.get_by_qid(node_name)[0]
        fmt_node_cmd = fmt_node.cmdline().strip("-blockdev ").strip("'")
        item = json.loads(fmt_node_cmd)
        qemu_binary = utils_misc.get_qemu_binary(self.params)
        qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
        required_qemu_version = self.params["required_qemu_version"]
        if qemu_version in VersionInterval(required_qemu_version):
            opts.append(item)
            args = {"options": opts}
            self.main_vm.monitor.blockdev_reopen(args)
        else:
            args = item
            self.main_vm.monitor.x_blockdev_reopen(args)

    def add_bitmap(self, node_name):
        bitmap = "bitmap_%s" % node_name
        kargs = {"bitmap_name": bitmap, "target_device": node_name}
        bitmap_handle.block_dirty_bitmap_add(self.main_vm, kargs)
        self.bitmap_list.append(kargs)

    def remove_bitmaps(self):
        actions = []
        bitmap_rm_cmd = self.params.get(
            "bitmap_remove_cmd", "block-dirty-bitmap-remove"
        )
        for item in self.bitmap_list:
            bitmap_data = {"node": item["target_device"], "name": item["bitmap_name"]}
            actions.append({"type": bitmap_rm_cmd, "data": bitmap_data})
        arguments = {"actions": actions}
        self.main_vm.monitor.cmd("transaction", arguments)

    def pre_test(self):
        self.bitmap_list = []
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        self.add_bitmap(self.params["node"])
        self.prepare_snapshot_file()
        self.create_snapshot()
        self.add_bitmap(self.params["overlay"])

    def post_test(self):
        self.snapshot_image.remove()

    def run_test(self):
        self.pre_test()
        try:
            self.reopen_backing_image(self.params["node"])
            self.remove_bitmaps()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Backup VM disk test when VM reboot

    1) start VM with system disk
    2) add a bitmap
    3) create snapshot target node
    4) do snapshot to target node
    5) add a bitmap to snapshot node
    6) reopen backing image by (x-)blockdev-reopen
    7) remove all bitmaps
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.update(
        {
            "image_name_%s" % base_image: params["image_name"],
            "image_format_%s" % base_image: params["image_format"],
        }
    )
    snapshot_test = BlkIncModifyBackingBitmaps(test, params, env)
    snapshot_test.run_test()
