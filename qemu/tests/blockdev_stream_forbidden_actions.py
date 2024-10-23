from virttest import data_dir
from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest
from provider.virt_storage.storage_admin import sp_admin


class BlockdevStreamForbiddenActionsTest(BlockdevStreamNowaitTest):
    """Do qmp commands during block-stream"""

    def __init__(self, test, params, env):
        super(BlockdevStreamForbiddenActionsTest, self).__init__(test, params, env)
        self._snapshot_images = self.params.objects("snapshot_images")
        self._trash = []

    def prepare_snapshot_file(self):
        """hotplug all snapshot images"""

        def _disk_define_by_params(tag):
            params = self.params.copy()
            params.setdefault("target_path", data_dir.get_data_dir())
            return sp_admin.volume_define_by_params(tag, params)

        for tag in self._snapshot_images:
            disk = _disk_define_by_params(tag)
            disk.hotplug(self.main_vm)
            self._trash.append(disk)

    def post_test(self):
        list(map(sp_admin.remove_volume, self._trash))

    def commit(self):
        self.main_vm.monitor.cmd("block-commit", {"device": self._top_device})

    def resize(self):
        self.main_vm.monitor.cmd(
            "block_resize", {"node-name": self._top_device, "size": 1024 * 1024 * 1024}
        )

    def mirror(self):
        self.main_vm.monitor.cmd(
            "blockdev-mirror",
            {
                "device": self._top_device,
                "target": self.params["overlay_node"],
                "sync": "full",
            },
        )

    def snapshot(self):
        self.main_vm.monitor.cmd(
            "blockdev-snapshot",
            {"node": self._top_device, "overlay": self.params["overlay_node"]},
        )

    def stream(self):
        self.main_vm.monitor.cmd("block-stream", {"device": self._top_device})

    def do_forbidden_actions(self):
        """Run the qmp commands one by one, all should fail"""
        for action in self.params.objects("forbidden_actions"):
            error_msg = self.params["error_msg_%s" % action]
            f = getattr(self, action)
            try:
                f()
            except QMPCmdError as e:
                if error_msg not in str(e):
                    self.test.fail("Unexpected error: %s" % str(e))
            else:
                self.test.fail("Unexpected qmp command success")

    def do_test(self):
        self.create_snapshot()
        self.blockdev_stream()
        self.do_forbidden_actions()
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._job, "speed": 0}
        )
        self.wait_stream_job_completed()


def run(test, params, env):
    """
    Basic block stream test with stress
    test steps:
        1. boot VM with a data image
        2. add snapshot images
        3. take snapshots(data->sn1)
        4. do block-stream
        5. do some qmp commands, all should fail
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamForbiddenActionsTest(test, params, env)
    stream_test.run_test()
