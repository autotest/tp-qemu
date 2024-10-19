import json
import time

from provider import backup_utils
from provider.blockdev_snapshot_base import BlockDevSnapshotTest


class BlockDevStreamTest(BlockDevSnapshotTest):
    def __init__(self, test, params, env):
        super(BlockDevStreamTest, self).__init__(test, params, env)
        self._stream_options = {}
        self._top_device = "drive_%s" % self.snapshot_tag
        self._init_stream_options()
        if self.base_tag == self.params.objects("images")[0]:
            self.disks_info[self.base_tag] = [
                "system",
                self.params.get("mnt_on_sys_dsk", "/var/tmp"),
            ]

    def _init_stream_options(self):
        if self.params.get("speed"):
            self._stream_options["speed"] = int(self.params["speed"])
        if self.params.get("base"):
            self._stream_options["base"] = self.params["base"]
        if self.params.get("base_node"):
            self._stream_options["base-node"] = self.params["base_node"]
        if self.params.get("on_error"):
            self._stream_options["on-error"] = self.params["on_error"]
        if self.params.get("auto_finalize"):
            self._stream_options["auto-finalize"] = self.params["auto_finalize"]
        if self.params.get("auto_dismiss"):
            self._stream_options["auto-dismiss"] = self.params["auto_dismiss"]
        if self.params.get("backing_file"):
            self._stream_options["backing-file"] = self.params["backing_file"]
        if self.params.get("block_stream_timeout"):
            self._stream_options["timeout"] = int(self.params["block_stream_timeout"])

    def snapshot_test(self):
        for info in self.disks_info.values():
            self.generate_tempfile(info[1], filename="base")
        self.create_snapshot()
        for info in self.disks_info.values():
            self.generate_tempfile(info[1], filename="sn1")

    def blockdev_stream(self):
        if not self.is_blockdev_mode():
            self._stream_options["base"] = self.base_image.image_filename
            self._top_device = self.params["device"]
        backup_utils.blockdev_stream(
            self.main_vm, self._top_device, **self._stream_options
        )
        time.sleep(0.5)

    def check_backing_file(self):
        self.main_vm.destroy()
        out = self.snapshot_image.info(output="json")
        info = json.loads(out)
        backing_file = info.get("backing-filename")
        assert not backing_file, "Unexpect backing file(%s) found!" % backing_file

    def mount_data_disks(self):
        if self.base_tag != self.params.objects("images")[0]:
            super(BlockDevStreamTest, self).mount_data_disks()

    def remove_files_from_system_image(self, tmo=60):
        """Remove testing files from system image"""
        if self.base_tag == self.params.objects("images")[0]:
            files = ["%s/%s" % (info[0], info[1]) for info in self.files_info]
            if files:
                self.main_vm = self.main_vm.clone()
                self.main_vm.create()
                self.main_vm.verify_alive()

                try:
                    session = self.main_vm.wait_for_login()
                    session.cmd("rm -f %s" % " ".join(files), timeout=tmo)
                    session.close()
                finally:
                    self.main_vm.destroy()

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_backing_file()
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()

    def run_test(self):
        self.pre_test()
        try:
            self.do_test()
        finally:
            self.post_test()
