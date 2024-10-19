import logging

from avocado.utils import memory
from virttest import error_context

from provider import backup_utils, blockdev_full_backup_base

LOG_JOB = logging.getLogger("avocado.test")


class BlockDevFullMirrorTest(blockdev_full_backup_base.BlockdevFullBackupBaseTest):
    @error_context.context_aware
    def blockdev_mirror(self):
        source = "drive_%s" % self.source_disks[0]
        target = "drive_%s" % self.target_disks[0]
        try:
            error_context.context(
                "backup %s to %s, options: %s" % (source, target, self.backup_options),
                LOG_JOB.info,
            )
            backup_utils.blockdev_mirror(
                self.main_vm, source, target, **self.backup_options
            )
        finally:
            memory.drop_caches()

    def verify_blockdev_mirror(self):
        out = self.main_vm.monitor.query("block")
        target_node = "drive_%s" % self.target_disks[0]
        for item in out:
            inserted = item["inserted"]
            if self.is_blockdev_mode():
                device = inserted.get("node-name")
            else:
                device = inserted.get("device")
            if device == target_node:
                return
        self.test.fail("target node(%s) is not opening" % target_node)

    @error_context.context_aware
    def do_backup(self):
        """Backup source image to target image"""
        self.blockdev_mirror()
        self.verify_blockdev_mirror()
        self.verify_target_disk()


def run(test, params, env):
    """
    mirror block device to target:
    1). boot guest with data disk with different cluster size
    2). create data file in data disk and save md5sum
    3). create target disk with different cluster size
    4). mirror block device from data disk to target disk
    5). boot guest with target disk
    6). verify data md5sum in data disk

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    mirror_test = BlockDevFullMirrorTest(test, params, env)
    mirror_test.run_test()
