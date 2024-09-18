import json

from avocado.utils import process
from virttest.utils_numeric import normalize_data_size

from provider.block_dirty_bitmap import block_dirty_bitmap_add
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkBitmapSizeTest(BlockdevLiveBackupBaseTest):
    """Estimate bitmaps size"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkBitmapSizeTest, self).__init__(test, params, env)
        self._granularities = self.params.objects("granularity_list")

    def add_bitmaps(self):
        args = {"target_device": self._source_nodes[0], "persistent": "on"}
        if self._granularities:
            for granularity in self._granularities:
                g = int(normalize_data_size(granularity, "B"))
                args.update({"bitmap_name": "bitmap_%s" % g, "bitmap_granularity": g})
                block_dirty_bitmap_add(self.main_vm, args)
        else:
            max_len = self.params.get_numeric("max_bitmap_name_len")
            for i in range(self.params.get_numeric("bitmap_count")):
                l = max_len - len(str(i))
                args["bitmap_name"] = process.run(
                    self.params["create_bitmap_name_cmd"].format(length=l),
                    ignore_status=True,
                    shell=True,
                ).stdout.decode().strip() + str(i)
                block_dirty_bitmap_add(self.main_vm, args)

    def measure_bitmaps_size(self):
        img = self.source_disk_define_by_params(self.params, self._source_images[0])
        o = img.measure(self.params["target_fmt"], output="json").stdout_text
        if o:
            info = json.loads(o)
            if info.get(self.params["check_keyword"], 0) <= 0:
                self.test.fail("Failed to get bitmap size")
        else:
            self.test.error("Failed to measure a qcow2 image")

    def prepare_test(self):
        self.prepare_main_vm()

    def do_test(self):
        self.add_bitmaps()
        self.main_vm.destroy()
        self.measure_bitmaps_size()


def run(test, params, env):
    """
    Estimate bitmaps size

    test steps:
        1. boot VM with a 2G data disk
        2. add bitmaps with default granularity or different granularities
        3. measure bitmaps size with qemu-img

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkBitmapSizeTest(test, params, env)
    inc_test.run_test()
