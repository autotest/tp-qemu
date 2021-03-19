from provider.backup_utils import full_backup, incremental_backup
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.job_utils import wait_until_block_job_completed


class BlockdevIncbkIncWithRecoveredBitmap(BlockdevLiveBackupBaseTest,
                                          BlockDevSnapshotTest):
    """Do incremental backup with recovered bitmap"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkIncWithRecoveredBitmap, self).__init__(test,
                                                                  params,
                                                                  env)
        self.snapshot_tag = params["snapshot_tag"]
        self.snapshot_node = "drive_%s" % params["snapshot_tag"]
        self.base_tag = params["base_tag"]
        self.snapshot_image = self.get_image_by_tag(self.snapshot_tag)
        self.base_image = self.get_image_by_tag(self.base_tag)
        self._inc_bk_nodes = ["drive_%s" % t for t in self._target_images]

    def do_full_backup(self):
        full_backup(self.main_vm, self._source_nodes[0],
                    self._full_bk_nodes[0])

    def do_incremental_backup(self):
        incremental_backup(self.main_vm, self._source_nodes[0],
                           self._inc_bk_nodes[0], self._bitmaps[0])

    def add_target_data_disks(self):
        # Add backup images
        super(BlockdevIncbkIncWithRecoveredBitmap,
              self).add_target_data_disks()

        # Add snapshot image
        disk = self.target_disk_define_by_params(self.params,
                                                 self.snapshot_tag)
        disk.hotplug(self.main_vm)
        self.trash.append(disk)

    def recover_bitmap_chain(self):
        """create an bitmap and populate it"""

        create_cmd = self.main_vm.monitor.get_workable_cmd(
            "block-dirty-bitmap-create")
        populate_cmd = self.main_vm.monitor.get_workable_cmd(
            "block-dirty-bitmap-populate")
        jobid = "populate_job"
        self.main_vm.monitor.cmd(create_cmd,
                                 {"node": self.snapshot_node,
                                  "name": self._bitmaps[0]})
        self.main_vm.monitor.cmd(populate_cmd,
                                 {"node": self.snapshot_node,
                                  "name": self._bitmaps[0],
                                  "job-id": jobid})
        wait_until_block_job_completed(self.main_vm, jobid)

    def rebase_inc_onto_full(self):
        # rebase 'inc' image onto 'full' image
        disk = self.source_disk_define_by_params(self.params,
                                                 self.snapshot_tag)
        disk.rebase(params=self.params)

    def do_test(self):
        self.do_full_backup()
        self.create_snapshot()
        self.generate_inc_files()
        self.recover_bitmap_chain()
        self.do_incremental_backup()
        self.main_vm.destroy()
        self.rebase_inc_onto_full()
        self.prepare_clone_vm()
        self.verify_data_files()


def run(test, params, env):
    """
    Do incremental backup with recovered bitmap

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. hotplug target disks for backup(full/inc) and snapshot(snap)
        4. do full backup(data1->full, don't add bitmap here)
        5. create snapshot(data1->snap)
        6. create another file (size 110M)
        7. recover bitmap chain
           create a bitmap
           populate the bitmap to snap image
        8. do inc bakcup(snap->inc)
        9. stop VM and rebase inc onto full
       10. restart VM and check the file checksum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkIncWithRecoveredBitmap(test, params, env)
    inc_test.run_test()
