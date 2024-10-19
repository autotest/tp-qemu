import logging
import time
from functools import partial

from virttest import error_context

from provider import backup_utils, block_dirty_bitmap, job_utils
from qemu.tests import live_backup_base

LOG_JOB = logging.getLogger("avocado.test")


class DifferentialBackupTest(live_backup_base.LiveBackup):
    def __init__(self, test, params, env, tag):
        super(DifferentialBackupTest, self).__init__(test, params, env, tag)
        self.device = "drive_%s" % tag

    def generate_backup_params(self):
        """generate target image params"""
        pass

    def init_data_disk(self):
        """Initialize the data disk"""
        session = self.get_session()
        get_disk_cmd = self.params["get_disk_cmd"]
        disk = session.cmd_output(get_disk_cmd).strip()
        for item in ["format_disk_cmd", "mount_disk_cmd"]:
            cmd = self.params[item].replace("DISK", disk)
            session.cmd(cmd)
            time.sleep(0.5)
        session.close()

    def get_record_counts_of_bitmap(self, name):
        """
        Get record counts of bitmap in the device

        :param name: bitmap name
        :return: record counts
        :rtype: int
        """
        bitmap = block_dirty_bitmap.get_bitmap_by_name(self.vm, self.device, name)
        return bitmap["count"] if bitmap else -1

    def get_sha256_of_bitmap(self, name):
        """
        Return sha256 value of bitmap in the device

        :param name: bitmap name
        """
        kwargs = {"vm": self.vm, "device": self.device, "bitmap": name}
        return block_dirty_bitmap.debug_block_dirty_bitmap_sha256(**kwargs)

    def _make_bitmap_transaction_action(
        self, operator="add", index=1, extra_options=None
    ):
        bitmap = "bitmap_%d" % index
        action = "block-dirty-bitmap-%s" % operator
        action = self.vm.monitor.get_workable_cmd(action)
        data = {"node": self.device, "name": bitmap}
        if isinstance(extra_options, dict):
            data.update(extra_options)
        LOG_JOB.debug("%s bitmap %s", operator.capitalize, bitmap)
        return job_utils.make_transaction_action(action, data)

    def _bitmap_batch_operate_by_transaction(self, action, bitmap_index_list):
        bitmap_lists = ",".join(map(lambda x: "bitmap_%d" % x, bitmap_index_list))
        LOG_JOB.info("%s %s in a transaction", action.capitalize(), bitmap_lists)
        func = partial(self._make_bitmap_transaction_action, action)
        actions = list(map(func, bitmap_index_list))
        return self.vm.monitor.transaction(actions)

    def _track_file_with_bitmap(self, filename, action_items):
        """
        Track file with bitmap

        :param filename: full path of file will create
        :param action_items: list of bitmap action.
                             eg, [{"operator": "add", "index": 1}
        """
        full_name = "%s/%s" % (self.params.get("mount_point", "/mnt"), filename)
        self.create_file(full_name)
        actions = list(
            [self._make_bitmap_transaction_action(**item) for item in action_items]
        )
        self.vm.monitor.transaction(actions)

    def track_file1_with_bitmap2(self):
        """track file1 with bitmap2"""
        action_items = [
            {"operator": "disable", "index": 2},
            {"operator": "add", "index": 3},
        ]
        self._track_file_with_bitmap("file1", action_items)

    def track_file2_with_bitmap3(self):
        """track file2 with bitmap3"""
        action_items = [
            {"operator": "disable", "index": 1},
            {"operator": "disable", "index": 3},
        ]
        self._track_file_with_bitmap("file2", action_items)

    def merge_bitmap2_and_bitmap3_to_bitmap4(self):
        """merged bitmap2 and bitmap3 into bitmap4"""
        source_bitmaps, target_bitmap = ["bitmap_2", "bitmap_3"], "bitmap_4"
        args = {
            "bitmap_name": target_bitmap,
            "target_device": self.device,
            "disabled": "on",
        }
        block_dirty_bitmap.block_dirty_bitmap_add(self.vm, args)
        block_dirty_bitmap.block_dirty_bitmap_merge(
            self.vm, self.device, source_bitmaps, target_bitmap
        )
        time.sleep(5)

    def track_file3_with_bitmap5(self):
        """track file3 with bitmap5"""
        args = {"bitmap_name": "bitmap_5", "target_device": self.device}
        block_dirty_bitmap.block_dirty_bitmap_add(self.vm, args)
        full_name = "%s/file3" % self.params.get("mount_point", "/mnt")
        self.create_file(full_name)

    def merge_bitmap5_to_bitmap4(self):
        source_bitmaps, target_bitmap = ["bitmap_5"], "bitmap_4"
        return block_dirty_bitmap.block_dirty_bitmap_merge(
            self.vm, self.device, source_bitmaps, target_bitmap
        )

    def do_full_backup(self, tag):
        """Do full backup"""
        target = backup_utils.create_image_by_params(self.vm, self.params, tag)
        node_name = target.format.get_param("node-name")
        # Notes:
        #    We use data disk in this case, so here not need to
        # pause VM to stop IO for ensure data integrity
        self._bitmap_batch_operate_by_transaction("add", [1, 2])
        backup_utils.full_backup(self.vm, self.device, node_name)
        self.trash_files.append(target.key)
        return node_name

    def do_incremental_backup_with_bitmap4(self, base_node, tag):
        """Do incremental backup with bitmap4"""
        img = backup_utils.create_image_by_params(self.vm, self.params, tag)
        node_name = img.format.get_param("node-name")
        backup_utils.incremental_backup(self.vm, self.device, node_name, "bitmap_4")
        self.trash_files.append(img.key)

    def clean(self):
        """Stop bitmaps and clear image files"""
        block_dirty_bitmap.clear_all_bitmaps_in_device(self.vm, self.device)
        block_dirty_bitmap.remove_all_bitmaps_in_device(self.vm, self.device)
        super(DifferentialBackupTest, self).clean()


@error_context.context_aware
def run(test, params, env):
    """
    Differential Backup Test
    1). boot VM with 2G data disk
    2). create bitmap1, bitmap2 to track changes in data disk
    3). do full backup for data disk
    4). create file1 in data disk and track it with bitmap2
    5). create file2 in data disk and track it with bitmap3
    6). merge bitmap2 and bitmap3 to bitmap4
    7). create file3 in data disk and track it with bitmap5
    8). merge bitmap5 to bitmap4
    9). do incremental backup with bitmap4
    10). reset and remove all bitmaps

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image2")
    backup_test = DifferentialBackupTest(test, params, env, tag)
    try:
        error_context.context("Initialize data disk", test.log.info)
        backup_test.init_data_disk()
        error_context.context("Do full backup", test.log.info)
        node_name = backup_test.do_full_backup("full")
        error_context.context("track file1 in bitmap2", test.log.info)
        backup_test.track_file1_with_bitmap2()
        error_context.context("track file2 in bitmap3", test.log.info)
        backup_test.track_file2_with_bitmap3()
        error_context.context("Record counts & sha256 of bitmap1", test.log.info)
        sha256_bitmap1 = backup_test.get_sha256_of_bitmap("bitmap_1")
        record_counts_bitmap1 = backup_test.get_record_counts_of_bitmap("bitmap_1")
        error_context.context("Merge bitmap2 and bitmap3 to bitmap4", test.log.info)
        backup_test.merge_bitmap2_and_bitmap3_to_bitmap4()
        error_context.context("Record sha256 of bitmap4", test.log.info)
        sha256_bitmap4 = backup_test.get_sha256_of_bitmap("bitmap_4")
        error_context.context("Record count of bitmap4", test.log.info)
        record_counts_bitmap4 = backup_test.get_record_counts_of_bitmap("bitmap_4")
        if sha256_bitmap4 != sha256_bitmap1:
            test.log.debug(
                "sha256_bitmap1: %s, sha256_bitmap4: %s", sha256_bitmap1, sha256_bitmap4
            )
            raise test.fail("sha256 of bitmap4 not equal sha256 of bitmap1")
        if record_counts_bitmap4 != record_counts_bitmap1:
            test.log.debug(
                "count_bitmap1: %d, count_bitmap4: %d",
                record_counts_bitmap1,
                record_counts_bitmap4,
            )
            raise test.fail("counts of bitmap4 not equal counts of bitmap4")
        error_context.context("track file3 in bitmap5", test.log.info)
        backup_test.track_file3_with_bitmap5()
        error_context.context("Merge bitmap5 in bitmap4", test.log.info)
        backup_test.merge_bitmap5_to_bitmap4()
        error_context.context("Do incremental backup with bitmap4", test.log.info)
        backup_test.do_incremental_backup_with_bitmap4(node_name, "inc")
    finally:
        backup_test.clean()
