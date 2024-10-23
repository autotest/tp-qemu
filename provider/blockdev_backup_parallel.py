from virttest import utils_misc

from provider.blockdev_backup_base import BlockdevBackupBaseTest


class BlockdevBackupParallelTest(BlockdevBackupBaseTest):
    def blockdev_backup(self):
        parallel_tests = self.params.objects("parallel_tests")
        targets = list([getattr(self, t) for t in parallel_tests if hasattr(self, t)])
        backup_func = super(BlockdevBackupParallelTest, self).blockdev_backup
        targets.append(backup_func)
        utils_misc.parallel(targets)
