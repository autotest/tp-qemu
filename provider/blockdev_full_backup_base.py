from provider.blockdev_backup_base import BlockdevBackupBaseTest


class BlockdevFullBackupBaseTest(BlockdevBackupBaseTest):
    def get_backup_options(self, params):
        extra_options = super(BlockdevFullBackupBaseTest, self).get_backup_options(
            params
        )
        extra_options["sync"] = "full"
        return extra_options

    def do_backup(self):
        """
        Backup source image to target image
        """
        self.blockdev_backup()
        self.verify_target_disk()

    def verify_target_disk(self):
        """
        Verify file in target disk same with file in source disk
        """
        self.prepare_clone_vm()
        try:
            self.verify_data_files()
        finally:
            self.clone_vm.destroy()
