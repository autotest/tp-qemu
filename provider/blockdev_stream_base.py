import time
import json

from provider import backup_utils
from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlockDevStreamTest(BlockDevSnapshotTest):

    def snapshot_test(self):
        for info in self.disks_info:
            self.generate_tempfile(info[1], filename="base")
        self.create_snapshot()
        for info in self.disks_info:
            self.generate_tempfile(info[1], filename="sn1")

    def blockdev_stream(self):
        arguments = {}
        if self.is_blockdev_mode():
            device = "drive_%s" % self.snapshot_tag
        else:
            device = self.params["device"]
            arguments["base"] = self.base_image.image_filename
        arguments["speed"] = int(self.params.get("speed", 0))
        backup_utils.blockdev_stream(self.main_vm, device, **arguments)
        time.sleep(0.5)

    def check_backing_file(self):
        self.main_vm.destroy()
        out = self.snapshot_image.info(output="json")
        info = json.loads(out)
        backing_file = info.get("backing-filename")
        assert not backing_file, "Unexpect backing file(%s) found!" % backing_file

    def run_test(self):
        self.pre_test()
        try:
            self.snapshot_test()
            self.blockdev_stream()
            self.check_backing_file()
            self.clone_vm.create()
            self.mount_data_disks()
            self.verify_data_file()
        finally:
            self.post_test()
