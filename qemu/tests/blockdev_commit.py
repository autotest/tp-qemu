from virttest import utils_disk

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockDevCommitBase(BlockDevCommitTest):
    def configure_data_disk(self, tag):
        session = self.main_vm.wait_for_login()
        try:
            info = backup_utils.get_disk_info_by_param(tag, self.params, session)
            assert info, "Disk not found in guest!"
            mount_point = utils_disk.configure_empty_linux_disk(
                session, info["kname"], info["size"]
            )[0]
            self.disks_info.append([r"/dev/%s1" % info["kname"], mount_point, tag])
        finally:
            session.close()


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    6. verify files's md5
    """

    block_test = BlockDevCommitBase(test, params, env)
    block_test.run_test()
