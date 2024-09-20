from avocado.utils import memory

from provider import backup_utils
from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest
from provider.qsd import QsdDaemonDev


class QSDMirrorTest(BlockdevMirrorWaitTest):
    def __init__(self, test, params, env):
        super(QSDMirrorTest, self).__init__(test, params, env)
        self._source_nodes = ["fmt_%s" % src for src in self._source_images]

    def get_qsd_demon(self):
        qsd_name = self.params["qsd_namespaces"]
        qsd_ins = QsdDaemonDev(qsd_name, self.params)
        return qsd_ins

    def start_qsd(self):
        self.qsd = self.get_qsd_demon()
        self.qsd.start_daemon()

    def add_target_data_disks(self):
        """Hot plug target disks to VM with qmp monitor"""
        for tag in self._target_images:
            disk = self.target_disk_define_by_params(
                self.params.object_params(tag), tag
            )
            disk.hotplug(self.qsd)
            self.trash.append(disk)

    def blockdev_mirror(self):
        """Run block-mirror and wait job done"""
        try:
            for idx, source_node in enumerate(self._source_nodes):
                backup_utils.blockdev_mirror(
                    self.qsd,
                    source_node,
                    self._target_nodes[idx],
                    **self._backup_options[idx],
                )
        finally:
            memory.drop_caches()

    def _check_mirrored_block_node_attached(self, source_qdev, target_node):
        out = self.qsd.monitor.cmd("query-named-block-nodes")[0]
        if out.get("node-name") != target_node:
            self.test.fail("Device is not attached to target node(%s)" % target_node)

    def clone_vm_with_mirrored_images(self):
        """Boot VM with mirrored data disks"""
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        if self.qsd.is_daemon_alive():
            self.qsd.stop_daemon()

        params = self.main_vm.params.copy()
        self.clone_vm = self.main_vm.clone(params=params)
        self.params.update({"qsd_images_qsd1": " ".join(self._target_images)})
        self.start_qsd()
        self.clone_vm.create()
        self.clone_vm.verify_alive()

        self.env.register_vm("%s_clone" % self.clone_vm.name, self.clone_vm)

    def prepare_test(self):
        self.start_qsd()
        super(QSDMirrorTest, self).prepare_test()

    def do_test(self):
        self.blockdev_mirror()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()

    def post_test(self):
        super(QSDMirrorTest, self).post_test()
        self.qsd.stop_daemon()


def run(test, params, env):
    """
    mirror block device to target:

    1). export data disk via qsd+nbd, then boot
    guest with the exported data disk
    2). create data file in data disk and save md5sum
    3). create target disk
    4). mirror block device from data disk to target disk
    5). export target disk via qsd+nbd, then boot guest
    with exported data disk
    6). verify data md5sum in data disk

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    mirror_test = QSDMirrorTest(test, params, env)
    mirror_test.run_test()
