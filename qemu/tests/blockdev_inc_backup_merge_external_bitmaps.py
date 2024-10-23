from provider.backup_utils import blockdev_batch_backup
from provider.block_dirty_bitmap import block_dirty_bitmap_merge
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlockdevIncbkMergeExternalBitmaps(BlockdevLiveBackupBaseTest):
    def __init__(self, test, params, env):
        super(BlockdevIncbkMergeExternalBitmaps, self).__init__(test, params, env)
        self._inc_bk_images = []
        self._inc_bk_nodes = []
        self._snapshot_images = []
        self._snapshot_nodes = []
        self._merged_bitmaps = []
        list(map(self._init_inc_arguments_by_params, self._source_images))

    def _init_inc_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        image_chain = image_params.objects("image_backup_chain")
        snapshot_img = image_params["snapshot_tag"]
        self._inc_bk_nodes.append("drive_%s" % image_chain[1])
        self._inc_bk_images.append(image_chain[1])
        self._snapshot_images.append(snapshot_img)
        self._snapshot_nodes.append("drive_%s" % snapshot_img)
        self._merged_bitmaps.append("bitmap_%s" % snapshot_img)

    def do_incremental_backup(self):
        extra_options = {"sync": "incremental"}
        blockdev_batch_backup(
            self.main_vm,
            self._snapshot_nodes,
            self._inc_bk_nodes,
            self._merged_bitmaps,
            **extra_options,
        )

    def do_snapshot(self):
        snapshots = []
        bitmaps = []
        for i, tag in enumerate(self._snapshot_images):
            disk = self.target_disk_define_by_params(self.params, tag)
            self.trash.append(disk)
            disk.hotplug(self.main_vm)

            snapshots.append(
                {
                    "type": "blockdev-snapshot",
                    "data": {
                        "node": self._source_nodes[i],
                        "overlay": self._snapshot_nodes[i],
                    },
                }
            )
            bitmaps.append(
                {
                    "type": "block-dirty-bitmap-add",
                    "data": {
                        "node": self._snapshot_nodes[i],
                        "name": self._merged_bitmaps[i],
                    },
                }
            )
        self.main_vm.monitor.transaction(snapshots + bitmaps)

    def merge_external_bitmaps(self):
        for i, node in enumerate(self._snapshot_nodes):
            block_dirty_bitmap_merge(
                self.main_vm,
                node,
                [{"node": self._source_nodes[i], "name": self._bitmaps[i]}],
                self._merged_bitmaps[i],
            )

    def do_test(self):
        self.do_full_backup()
        self.generate_inc_files("inc1")
        self.do_snapshot()
        self.generate_inc_files("inc2")
        self.merge_external_bitmaps()
        self.main_vm.pause()
        self.do_incremental_backup()
        self.prepare_clone_vm()
        self.verify_data_files()


def run(test, params, env):
    """
    Merge external bitmaps

    test steps:
        1. boot VM with a 2G data disk
        2. format data disk and mount it, create a file
        3. add target disks for backup to VM via qmp commands
        4. do full backup and add non-persistent bitmap
        5. create another file
        6. create source image's snapshot
        7. create another file
        8. merge source image's bitmap to its snapshot's bitmap
        9. pause vm
       10. do inc bakcup(sync: incremental)
       11. restart VM with inc image, check md5

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    inc_test = BlockdevIncbkMergeExternalBitmaps(test, params, env)
    inc_test.run_test()
