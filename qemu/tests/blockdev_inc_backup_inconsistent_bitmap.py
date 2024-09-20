import signal

from virttest.data_dir import get_data_dir
from virttest.qemu_monitor import QMPCmdError
from virttest.utils_misc import kill_process_tree

from provider.block_dirty_bitmap import (
    block_dirty_bitmap_add,
    block_dirty_bitmap_remove,
    get_bitmap_by_name,
)
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkInconsistentBitmap(BlockdevLiveBackupBaseTest):
    """Inconsistent bitmap tests"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkInconsistentBitmap, self).__init__(test, params, env)
        self._data_image_obj = self.source_disk_define_by_params(
            self.params, self._source_images[0]
        )
        self.test_scenario = getattr(self, self.params["test_scenario"])

    def prepare_test(self):
        self.prepare_main_vm()
        self.prepare_data_disks()

    def add_persistent_bitmap(self):
        kargs = {
            "bitmap_name": self._bitmaps[0],
            "target_device": self._source_nodes[0],
            "persistent": "on",
        }
        block_dirty_bitmap_add(self.main_vm, kargs)

    def is_image_bitmap_existed(self):
        out = self._data_image_obj.info()
        return out and self._bitmaps[0] in out

    def check_bitmap_field(self, **args):
        bitmap = get_bitmap_by_name(
            self.main_vm, self._source_nodes[0], self._bitmaps[0]
        )
        if bitmap is None:
            self.test.fail("Failed to get bitmap %s" % self._bitmaps[0])
        else:
            for key, value in args.items():
                if value != bitmap[key]:
                    self.test.fail(
                        "bitmap field %s is not correct: "
                        "expected %s, got %s" % (key, value, bitmap[key])
                    )

    def kill_qemu_and_start_vm(self):
        """Forcely killing qemu-kvm can make bitmap inconsistent"""

        kill_process_tree(self.main_vm.get_pid(), signal.SIGKILL, timeout=20)
        self.main_vm.create()
        self.main_vm.verify_alive()

    def powerdown_and_start_vm(self):
        self.main_vm.monitor.system_powerdown()
        if not self.main_vm.wait_for_shutdown(
            self.params.get_numeric("shutdown_timeout", 360)
        ):
            self.test.fail("Failed to poweroff vm")
        self.main_vm.create()
        self.main_vm.verify_alive()

    def handle_bitmap_with_qmp_cmd(self):
        """Failed to clear/enable/disable an inconsistent bitmap"""

        forbidden_actions = [
            "block-dirty-bitmap-disable",
            "block-dirty-bitmap-enable",
            "block-dirty-bitmap-clear",
        ]
        for action in forbidden_actions:
            try:
                self.main_vm.monitor.cmd(
                    action, {"node": self._source_nodes[0], "name": self._bitmaps[0]}
                )
            except QMPCmdError as e:
                error_msg = self.params["error_msg"] % self._bitmaps[0]
                if error_msg not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("%s completed unexpectedly" % action)

    def remove_bitmap_with_qmp_cmd(self):
        """Removing an inconsistent bitmap should succeed"""

        block_dirty_bitmap_remove(self.main_vm, self._source_nodes[0], self._bitmaps[0])
        bitmap = get_bitmap_by_name(
            self.main_vm, self._source_nodes[0], self._bitmaps[0]
        )
        if bitmap is not None:
            self.test.fail("Failed to remove bitmap %s" % self._bitmaps[0])

    def repair_bitmap_with_qemu_img(self):
        """Repair an inconsistent bitmap with qemu-img should succeed"""

        self.main_vm.destroy()
        if not self.is_image_bitmap_existed():
            self.test.fail("Persistent bitmap should exist in image")
        self._data_image_obj.check(self._data_image_obj.params, get_data_dir())
        if self.is_image_bitmap_existed():
            self.test.fail("Persistent bitmap should be removed from image")

    def do_test(self):
        self.add_persistent_bitmap()
        self.generate_inc_files(filename="inc")
        self.powerdown_and_start_vm()
        self.check_bitmap_field(recording=True)
        self.kill_qemu_and_start_vm()
        self.check_bitmap_field(recording=False, inconsistent=True)
        self.test_scenario()


def run(test, params, env):
    """
    Inconsistent bitmap tests

    test steps:
        1. boot VM with a 2G data disk
        2. add persistent bitmap, dd a file
        3. restart VM, then kill qemu-kvm
        4. restart VM, check bitmap is inconsistent
        5. Do some tests:
            5.1 clearing/enabling/disabling an inconsistent bitmap should fail
            5.2 removing an inconsistent bitmap should succeed
            5.3 removing an inconsistent bitmap with qemu-img should succeed

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkInconsistentBitmap(test, params, env)
    inc_test.run_test()
