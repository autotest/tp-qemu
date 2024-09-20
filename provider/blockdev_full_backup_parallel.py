from provider.blockdev_backup_parallel import BlockdevBackupParallelTest
from provider.blockdev_full_backup_base import BlockdevFullBackupBaseTest


class BlockdevFullBackupParallelTest(
    BlockdevFullBackupBaseTest, BlockdevBackupParallelTest
):
    pass
