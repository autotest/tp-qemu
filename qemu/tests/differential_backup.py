import time
import logging
from functools import partial

from virttest import error_context
from provider import block_dirty_bitmap
from provider import backup_utils
from qemu.tests import live_backup_base


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
        for cmd in ["format_disk_cmd", "mount_disk_cmd"]:
            if self.params.get(cmd):
                session.cmd(self.params[cmd])
                time.sleep(0.5)
        session.close()

    def get_record_counts_of_bitmap(self, name):
        """
        Get record counts of bitmap in the device

        :param name: bitmap name
        :return: record counts
        :rtype: int
        """
        bitmap = block_dirty_bitmap.get_bitmap_by_name(
            self.vm, self.device, name)
        return bitmap["count"] if bitmap else -1

    def get_sha256_of_bitmap(self, name):
        """
        Return sha256 value of bitmap in the device

        :param name: bitmap name
        """
        kwargs = {"vm": self.vm, "device": self.device, "bitmap": name}
        return block_dirty_bitmap.debug_block_dirty_bitmap_sha256(**kwargs)

    def _make_bitmap_transaction_action(
            self, operator="add", index=1, extra_options=None):
        bitmap = "bitmap_%d" % index
        action = "block-dirty-bitmap-%s" % operator
        data = {"node": self.device, "name": bitmap}
        if isinstance(extra_options, dict):
            data.update(extra_options)
        logging.debug("%s bitmap %s" % (operator.capitalize, bitmap))
        return backup_utils.make_transaction_action(action, data)

    def _bitmap_batch_operate_by_transaction(self, action, bitmap_index_list):
        bitmap_lists = ",".join(
            map(lambda x: "bitmap_%d" % x, bitmap_index_list))
        logging.info("%s %s in a transaction" %
                     (action.capitalize(), bitmap_lists))
        func = partial(self._make_bitmap_transaction_action, action)
        actions = map(func, bitmap_index_list)
        return self.vm.monitor.transaction(actions)

    def _track_file_with_bitmap(self, filename, action_items):
        """
        Track file with bitmap

        :param filename: full path of file will create
        :param action_items: list of bitmap action.
                             eg, [{"action": add, "index": 1}
        """
        self.create_file(filename)
        actions = []
        for item in action_items:
            action = item["action"]
            index = item["index"]
            actions += [self._make_bitmap_transaction_action(action, index)]
        self.vm.monitor.transaction(actions)

    def track_file1_with_bitmap2(self):
        """track file1 with bitmap2"""
        action_items = [{"action": "disable", "index": 2},
                        {"action": "add", "index": 3}]
        self._track_file_with_bitmap("file1", action_items)

    def track_file2_with_bitmap3(self):
        """track file2 with bitmap3"""
        action_items = [{"action": "disable", "index": 1},
                        {"action": "disable", "index": 3}]
        self._track_file_with_bitmap("file2", action_items)

    def merge_bitmap2_and_bitmap3_to_bitmap4(self):
        """merged bitmap2 and bitmap3 into bitmap4"""
        source_bitmaps, target_bitmap = ["bitmap_2", "bitmap_3"], "bitmap_4"
        self.vm.monitor.block_dirty_bitmap_add(
            self.device, target_bitmap, disabled=True)
        block_dirty_bitmap.block_dirty_bitmap_merge(
            self.vm, self.device, source_bitmaps, target_bitmap)
        time.sleep(5)

    def track_file3_with_bitmap5(self):
        """track file3 with bitmap5"""
        self.vm.monitor.block_dirty_bitmap_add(self.device, "bitmap_5")
        self.create_file("file3")
        self.vm.monitor.block_dirty_bitmap_disable(self.device, "bitmap_5")

    def merge_bitmap5_to_bitmap4(self):
        source_bitmaps, target_bitmap = ["bitmap_5"], "bitmap_4"
        return block_dirty_bitmap.block_dirty_bitmap_merge(
            self.vm, self.device, source_bitmaps, target_bitmap)

    def do_full_backup(self, tag):
        """Do full backup"""
        backing_info = dict()
        params = self.params.object_params(tag)
        node_name, filename = backup_utils.create_target_block_device(
            self.vm, params, backing_info)
        if not node_name:
            out = self.vm.monitor.query_jobs()
            self.test.fail("Create target device failed, %s" % out)
        # Notes:
        #    We use data disk in this case, so here not need to
        # pause VM to stop IO for ensure data integrity
        self._bitmap_batch_operate_by_transaction("add", [1, 2])
        backup_utils.full_backup(self.vm, self.device, node_name)
        self.trash_files.append(filename)
        return node_name

    def do_incremental_backup_with_bitmap4(self, base_node, tag):
        """Do incremental backup with bitmap4"""
        params = self.params.object_params(tag)
        node_info = backup_utils.get_block_node_by_name(self.vm, base_node)
        backing = {
            "backing": base_node,
            "backing-file": node_info["image"]["filename"],
            "backing-fmt": node_info["image"]["format"]}
        node_name, filename = backup_utils.create_target_block_device(
            self.vm, params, backing)
        if not node_name:
            out = self.vm.monitor.query_jobs()
            raise self.test.fail("Create target device failed, %s" % out)
        backup_utils.incremental_backup(
            self.vm, self.device, node_name, "bitmap_4")
        self.trash_files.append(filename)

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
        error_context.context("Initialize data disk", logging.info)
        backup_test.init_data_disk()
        error_context.context("Do full backup", logging.info)
        node_name = backup_test.do_full_backup("full")
        error_context.context("track file1 in bitmap2", logging.info)
        backup_test.track_file1_with_bitmap2()
        error_context.context("track file2 in bitmap3", logging.info)
        backup_test.track_file2_with_bitmap3()
        error_context.context(
            "Record counts & sha256 of bitmap1", logging.info)
        sha256_bitmap1 = backup_test.get_sha256_of_bitmap("bitmap_1")
        record_counts_bitmap1 = backup_test.get_record_counts_of_bitmap(
            "bitmap_1")
        error_context.context(
            "Merge bitmap2 and bitmap3 to bitmap4", logging.info)
        backup_test.merge_bitmap2_and_bitmap3_to_bitmap4()
        error_context.context("Record sha256 of bitmap4", logging.info)
        sha256_bitmap4 = backup_test.get_sha256_of_bitmap("bitmap_4")
        error_context.context("Record count of bitmap4", logging.info)
        record_counts_bitmap4 = backup_test.get_record_counts_of_bitmap(
            "bitmap_4")
        if sha256_bitmap4 != sha256_bitmap1:
            logging.debug("sha256_bitmap1: %d, sha256_bitmap4: %d" %
                          (sha256_bitmap1, sha256_bitmap4))
            raise test.fail("sha256 of bitmap4 not equal sha256 of bitmap1")
        if record_counts_bitmap4 != record_counts_bitmap1:
            logging.debug("count_bitmap1: %d, count_bitmap4: %d" %
                          (record_counts_bitmap1, record_counts_bitmap4))
            raise test.fail("counts of bitmap4 not equal counts of bitmap4")
        error_context.context("track file3 in bitmap5", logging.info)
        backup_test.track_file3_with_bitmap5()
        error_context.context("Merge bitmap5 in bitmap4", logging.info)
        backup_test.merge_bitmap5_to_bitmap4()
        error_context.context(
            "Do incremental backup with bitmap4", logging.info)
        backup_test.do_incremental_backup_with_bitmap4(node_name, "inc")
    finally:
        backup_test.clean()
