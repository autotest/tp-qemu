import ast

from provider.block_dirty_bitmap import (
    block_dirty_bitmap_disable,
    debug_block_dirty_bitmap_sha256,
    get_bitmap_by_name,
)
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkMigrateNoBitmap(BlockdevLiveBackupBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncbkMigrateNoBitmap, self).__init__(test, params, env)
        self._bitmap_debugged = self.params.get_boolean("bitmap_debugged")
        self._bitmap_sha256 = None

    def migrate_vm(self):
        capabilities = ast.literal_eval(self.params["migrate_capabilities"])
        self.main_vm.migrate(
            self.params.get_numeric("mig_timeout"),
            self.params["migration_protocol"],
            migrate_capabilities=capabilities,
            env=self.env,
        )

    def check_bitmap_after_migration(self):
        bitmap = get_bitmap_by_name(
            self.main_vm, self._source_nodes[0], self._bitmaps[0]
        )
        if self._bitmap_debugged:
            if bitmap is None:
                self.test.fail("No persistent bitmap was found " "after migration")
            if bitmap.get("recording") is not False:
                self.test.fail("Persistent bitmap was not disabled " "after migration")
            v = debug_block_dirty_bitmap_sha256(
                self.main_vm, self._source_nodes[0], self._bitmaps[0]
            )
            if self._bitmap_sha256 != v:
                self.test.fail("Persistent bitmap sha256 changed " "after migration")
        else:
            if bitmap is not None:
                self.test.fail(
                    "Got non-persistent bitmap unexpectedly " "after migration"
                )

    def get_bitmap_sha256(self):
        if self._bitmap_debugged:
            v = debug_block_dirty_bitmap_sha256(
                self.main_vm, self._source_nodes[0], self._bitmaps[0]
            )
            if v is None:
                self.test.fail("Failed to get persistent bitmap sha256")
            self._bitmap_sha256 = v

    def disable_bitmap(self):
        block_dirty_bitmap_disable(
            self.main_vm, self._source_nodes[0], self._bitmaps[0]
        )

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files()
        self.disable_bitmap()
        self.get_bitmap_sha256()
        self.migrate_vm()
        self.check_bitmap_after_migration()


def run(test, params, env):
    """
    Do incremental live backup with bitmap after migrated on shared storage
    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for full backup to VM via qmp commands
        4. do full backup and add a bitmap(persistent/non-persistent)
        5. create another file
        6. disable the bitmap
        7. get persistent bitmap's sha256 value
        8. Migrate VM from src to dst, wait till it is finished
        9. For non-persistent bitmap:
           bitmap should not be found
           For persistent bitmap:
           disabled bitmap should be found, sha256 should not change
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkMigrateNoBitmap(test, params, env)
    inc_test.run_test()
