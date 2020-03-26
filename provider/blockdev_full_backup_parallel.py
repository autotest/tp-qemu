from provider import blockdev_backup_parallel
from provider import blockdev_full_backup_base


class BlockdevFullBackupParallelTest(
        blockdev_full_backup_base.BlockdevFullBackupBaseTest,
        blockdev_backup_parallel.BlockdevBackupParallelTest):
    pass
