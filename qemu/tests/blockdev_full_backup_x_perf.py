import json
import re
from random import randrange

from provider import backup_utils
from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest


class BlkFullBackupXperf(BlockdevLiveBackupBaseTest):
    def get_image_cluster_size(self):
        csize_parttern = self.params.get("cluster_size_pattern")
        image_name = self._source_images[0]
        image_params = self.params.object_params(image_name)
        image = self.source_disk_define_by_params(image_params, image_name)
        output = image.info(force_share=True)
        match = re.findall(csize_parttern, output)
        if match:
            return int(match[0])

    def do_full_backup(self):
        perf_options = json.loads(self.params["perf_ops"])
        max_workers = randrange(1, int(perf_options["max-workers"]))
        csize = self.get_image_cluster_size()
        if csize:
            max_chunk = randrange(csize, int(perf_options["max-chunk"]))
            extra_options = {"max-workers": max_workers, "max-chunk": max_chunk}
        else:
            extra_options = {"max-workers": max_workers}
        backup_utils.blockdev_backup(
            self.main_vm, self._source_nodes[0], self._full_bk_nodes[0], **extra_options
        )

    def do_test(self):
        self.do_full_backup()
        self.prepare_clone_vm()
        self.verify_data_files()


def run(test, params, env):
    """
    backup test with x-perf:

    1) start VM with data disk
    2) create data file in data disk and save md5 of it
    3) create target disk with qmp command
    4) full backup source disk to target disk with x-perf params
    5) shutdown VM
    6) boot VM with target disk
    7) check data file md5 not change in target disk

    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    backup_test = BlkFullBackupXperf(test, params, env)
    backup_test.run_test()
