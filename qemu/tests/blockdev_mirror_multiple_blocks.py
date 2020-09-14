import re

from virttest import utils_disk
from virttest import utils_misc

from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest


class BlockdevMirrorMultipleBlocksTest(BlockdevMirrorParallelTest):
    """do block-mirror for multiple disks in parallel"""

    def _get_data_disk_info(self, tag, session):
        """Get the disk id and size by serial or wwn in linux"""
        disk_params = self.params.object_params(tag)
        extra_params = disk_params["blk_extra_params"]
        drive_id = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
        drive_path = utils_misc.get_linux_drive_path(session, drive_id)
        return drive_path[5:], disk_params["image_size"]

    def format_data_disk(self, tag):
        session = self.main_vm.wait_for_login()
        try:
            disk_id, disk_size = self._get_data_disk_info(tag, session)
            mnt = utils_disk.configure_empty_linux_disk(session,
                                                        disk_id,
                                                        disk_size)[0]
            self.disks_info[tag] = ["/dev/%s1" % disk_id, mnt]
        finally:
            session.close()


def run(test, params, env):
    """
    Multiple block mirror simultaneously

    test steps:
        1. boot VM with two 2G data disks
        2. format data disks and mount it
        3. create a file on both disks
        4. add target disks for mirror to VM via qmp commands
        4. do block-mirror for both disks in parallel
        5. check mirrored disks are attached
        6. restart VM with mirrored disks, check files and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorMultipleBlocksTest(test, params, env)
    mirror_test.run_test()
