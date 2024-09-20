"""Live snpashot test with qsd exposed image"""

from virttest import data_dir, error_context

from provider.blockdev_snapshot_base import BlockDevSnapshotTest
from provider.qsd import QsdDaemonDev, add_vubp_into_boot
from provider.virt_storage.storage_admin import sp_admin


class QSDSnapshotTest(BlockDevSnapshotTest):
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

    def verify_snapshot(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        self.qsd.stop_daemon()
        self.snapshot_image.base_tag = self.base_tag
        self.snapshot_image.base_format = self.base_image.get_format()
        base_image_filename = self.base_image.image_filename
        self.snapshot_image.base_image_filename = base_image_filename
        self.snapshot_image.rebase(self.snapshot_image.params)
        self.params.update({"qsd_images_qsd1": self.snapshot_tag})
        self.start_qsd()
        self.clone_vm.params["extra_params"] = add_vubp_into_boot(
            self.snapshot_tag, self.params
        )
        self.clone_vm.create()
        self.clone_vm.verify_alive()
        if self.base_tag != "image1":
            self.mount_data_disks()
            self.verify_data_file()

    def pre_test(self):
        self.start_qsd()
        self.main_vm.params["extra_params"] = add_vubp_into_boot(
            self.base_tag, self.params
        )
        self.main_vm.create()
        super(QSDSnapshotTest, self).pre_test()

    def post_test(self):
        super(QSDSnapshotTest, self).post_test()
        self.qsd.stop_daemon()

    def create_snapshot(self):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        arguments = self.params.copy_from_keys(options)
        arguments.setdefault("overlay", "drive_%s" % self.snapshot_tag)
        return self.qsd.monitor.cmd(cmd, dict(arguments))


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Snapshot test with qsd image
    1) Start QSD and expose a data image
    2) Start VM with qsd exposed data image
    3) Create snapshot for the data disk via qsd
    4) Save a temp file and record md5sum
    5) Quit vm and stop QSD demon
    6) Rebase snapshot to base if needed
    7) Start QSD and expose then snapshot image, then
       boot VM with Snapshot image as data disk
    8) Check temp file md5sum

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    snapshot_test = QSDSnapshotTest(test, params, env)
    snapshot_test.run_test()
