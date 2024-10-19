from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorForbiddenActionsTest(BlockdevMirrorNowaitTest):
    """Do qmp commands during blockdev-mirror"""

    def commit(self):
        self.main_vm.monitor.cmd("block-commit", {"device": self._source_nodes[0]})

    def resize(self):
        self.main_vm.monitor.cmd(
            "block_resize",
            {"node-name": self._target_nodes[0], "size": 1024 * 1024 * 1024},
        )

    def mirror(self):
        self.main_vm.monitor.cmd(
            "blockdev-mirror",
            {
                "device": self._source_nodes[0],
                "target": self._target_nodes[0],
                "sync": "full",
            },
        )

    def snapshot(self):
        self.main_vm.monitor.cmd(
            "blockdev-snapshot",
            {"node": self._source_nodes[0], "overlay": self._target_nodes[0]},
        )

    def stream(self):
        self.main_vm.monitor.cmd("block-stream", {"device": self._source_nodes[0]})

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
        self.blockdev_mirror()
        self.do_forbidden_actions()
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._jobs[0], "speed": 0}
        )
        self.wait_mirror_jobs_completed()


def run(test, params, env):
    """
    Do qmp commands while doing block mirror

    test steps:
        1. boot VM with a data image
        2. hotplug mirror image(mirror1)
        3. do blockdev-mirror(from data1 to mirror1)
        4. do some qmp commands, all should fail with correct error msgs
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """

    mirror_test = BlockdevMirrorForbiddenActionsTest(test, params, env)
    mirror_test.run_test()
