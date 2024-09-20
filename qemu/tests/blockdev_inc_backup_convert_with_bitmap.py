from avocado.utils import process
from virttest.utils_misc import get_qemu_img_binary

from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkConvertWithBitmapsTest(BlockdevLiveBackupBaseTest):
    """Convert image with persistent bitmaps"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkConvertWithBitmapsTest, self).__init__(test, params, env)
        self._bitmaps = params.objects("bitmap_list")
        self._bitmap_states = [True, False]
        self._src_image = self.source_disk_define_by_params(
            self.params, self._source_images[0]
        )
        self._target_image = self.source_disk_define_by_params(
            self.params, self.params["convert_target"]
        )

    def prepare_test(self):
        self.prepare_main_vm()

    def add_persistent_bitmaps(self):
        bitmaps = [
            {
                "node": self._source_nodes[0],
                "name": b,
                "persistent": self._full_backup_options["persistent"],
                "disabled": s,
            }
            for b, s in zip(self._bitmaps, self._bitmap_states)
        ]
        job_list = [
            {"type": "block-dirty-bitmap-add", "data": data} for data in bitmaps
        ]
        self.main_vm.monitor.transaction(job_list)

    def convert_data_image_with_bitmaps(self):
        # TODO: bitmap option is not supported by qemu_storage.convert,
        # so run qemu-img command explictly to convert an qcow2 image to
        # the target local qcow2 image
        cmd = "{qemu_img} convert -f {fmt} -O {ofmt} --bitmaps {s} {t}".format(
            qemu_img=get_qemu_img_binary(self.params),
            fmt=self._src_image.image_format,
            ofmt=self._target_image.image_format,
            s=self._src_image.image_filename,
            t=self._target_image.image_filename,
        )
        process.system(cmd, ignore_status=False, shell=True)
        self.trash.append(self._target_image)

    def check_image_bitmaps_existed(self):
        check_list = ["name: %s" % b for b in self._bitmaps]
        info = self._target_image.info()
        if not all([b in info for b in check_list]):
            self.test.fail("Persistent bitmaps should exist in image")

    def do_test(self):
        self.add_persistent_bitmaps()
        self.main_vm.destroy()
        self.convert_data_image_with_bitmaps()
        self.check_image_bitmaps_existed()


def run(test, params, env):
    """
    Test for converting image with bitmaps

    test steps:
        1. boot VM with a 2G data disk
        2. add two persistent bitmaps(enabled/disabled)
        3. convert image
        4. check bitmaps should exist on the converted image

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkConvertWithBitmapsTest(test, params, env)
    inc_test.run_test()
