from virttest import utils_disk

from provider import block_dirty_bitmap as block_bitmap
from provider.blockdev_stream_base import BlockDevStreamTest


class BlkStreamWithDirtybitmap(BlockDevStreamTest):
    """Do block-stream with active layer attached a bitmap"""

    def check_bitmap_info(self):
        bitmap = block_bitmap.get_bitmap_by_name(
            self.main_vm, self._top_device, self.bitmap_name
        )
        if bitmap:
            count = bitmap["count"]
            return count

    def add_bitmap(self):
        self.bitmap_name = "bitmap_%s" % self.snapshot_tag
        kargs = {"bitmap_name": self.bitmap_name, "target_device": self._top_device}
        block_bitmap.block_dirty_bitmap_add(self.main_vm, kargs)

    def umount_data_disk(self):
        session = self.main_vm.wait_for_login()
        try:
            for info in self.disks_info.values():
                disk_path = info[0]
                mount_point = info[1]
                utils_disk.umount(disk_path, mount_point, session=session)
        finally:
            session.close()

    def snapshot_test(self):
        for info in self.disks_info.values():
            self.generate_tempfile(info[1], filename="base")
        self.create_snapshot()
        self.add_bitmap()
        for info in self.disks_info.values():
            self.generate_tempfile(info[1], filename="sn1")
        self.umount_data_disk()

    def do_test(self):
        self.snapshot_test()
        bcount_bstream = self.check_bitmap_info()
        self.blockdev_stream()
        bcount_astream = self.check_bitmap_info()
        if bcount_bstream != bcount_astream:
            self.test.fail(
                "bitmap count changed after stream with actual:%d "
                "expected:%d" % (bcount_astream, bcount_bstream)
            )


def run(test, params, env):
    """
    Do block stream with active layer attached a bitmap
    test steps:
        1. boot VM with a data image
        2. dd a file in data disk
        3. create snapshot
        4. add a bitmap to snapshot, write some data on it.
        5. check bitmap info
        6. do block stream
        7. check bitmap info

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlkStreamWithDirtybitmap(test, params, env)
    stream_test.run_test()
