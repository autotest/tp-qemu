import json
import time

from virttest import data_dir, error_context

from provider import backup_utils
from provider.blockdev_stream_base import BlockDevStreamTest
from provider.qsd import QsdDaemonDev, add_vubp_into_boot
from provider.virt_storage.storage_admin import sp_admin


class QSDStreamTest(BlockDevStreamTest):
    def get_qsd_demon(self):
        qsd_name = self.params["qsd_namespaces"]
        qsd_ins = QsdDaemonDev(qsd_name, self.params)
        return qsd_ins

    def start_qsd(self):
        self.qsd = self.get_qsd_demon()
        self.qsd.start_daemon()

    def prepare_snapshot_file(self):
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        image = sp_admin.volume_define_by_params(self.snapshot_tag, params)
        image.hotplug(self.qsd)

    def check_backing_file(self):
        self.main_vm.destroy()
        self.qsd.stop_daemon()
        out = self.snapshot_image.info(output="json")
        info = json.loads(out)
        backing_file = info.get("backing-filename")
        assert not backing_file, "Unexpect backing file(%s) found!" % backing_file

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.check_backing_file()
        self.params.update({"qsd_images_qsd1": self.snapshot_tag})
        self.start_qsd()
        self.clone_vm.params["extra_params"] = add_vubp_into_boot(
            self.snapshot_tag, self.params
        )
        self.clone_vm.create()
        self.mount_data_disks()
        self.verify_data_file()

    def pre_test(self):
        self.start_qsd()
        self.main_vm.params["extra_params"] = add_vubp_into_boot(
            self.base_tag, self.params
        )
        super(QSDStreamTest, self).pre_test()

    def create_snapshot(self):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        arguments = self.params.copy_from_keys(options)
        arguments.setdefault("overlay", "drive_%s" % self.snapshot_tag)
        return self.qsd.monitor.cmd(cmd, dict(arguments))

    def blockdev_stream(self):
        backup_utils.blockdev_stream(self.qsd, self._top_device, **self._stream_options)
        time.sleep(0.5)

    def post_test(self):
        super(QSDStreamTest, self).post_test()
        self.qsd.stop_daemon()


@error_context.context_aware
def run(test, params, env):
    """
    Test VM block device stream feature
    1) Start qsd and export an image
    2) Start VM with the exported image via qsd
    3) create file in data disk and save it's md5sum
    4) Create snapshot for the data disk
    5) Save a temp file and record md5sum
    6) stream the data disk, stop qsd, check its backing file
    7) Export snapshot image via qsd, start vm with the exported image
    8) Verify files' md5sum

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    stream_test = QSDStreamTest(test, params, env)
    stream_test.run_test()
