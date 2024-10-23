from virttest.qemu_monitor import QMPCmdError

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitForbiddenActions(BlockDevCommitTest):
    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["speed"]
        arguments = self.params.copy_from_keys(options)
        arguments["speed"] = self.params["commit_speed"]
        self.active_node = self.get_node_name(snapshot_tags[-1])
        self.forbidden_node = self.get_node_name(self.params["fnode"])
        commit_cmd = backup_utils.block_commit_qmp_cmd
        cmd, args = commit_cmd(self.active_node, **arguments)
        backup_utils.set_default_block_job_options(self.main_vm, args)
        self.main_vm.monitor.cmd(cmd, args)
        job_id = args.get("job-id", self.active_node)
        self.do_forbidden_actions()
        self.main_vm.monitor.cmd("block-job-set-speed", {"device": job_id, "speed": 0})
        job_utils.wait_until_block_job_completed(self.main_vm, job_id)

    def commit(self):
        self.main_vm.monitor.cmd("block-commit", {"device": self.active_node})

    def resize(self):
        self.main_vm.monitor.cmd(
            "block_resize", {"node-name": self.active_node, "size": 1024 * 1024 * 1024}
        )

    def mirror(self):
        self.main_vm.monitor.cmd(
            "blockdev-mirror",
            {"device": self.active_node, "target": self.forbidden_node, "sync": "full"},
        )

    def snapshot(self):
        self.main_vm.monitor.cmd(
            "blockdev-snapshot",
            {"node": self.active_node, "overlay": self.forbidden_node},
        )

    def stream(self):
        self.main_vm.monitor.cmd("block-stream", {"device": self.active_node})

    def do_forbidden_actions(self):
        """Run the qmp commands one by one, all should fail"""
        self.prepare_snapshot_file(self.params["fnode"].split())
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


def run(test, params, env):
    """
    Snapshot related action should be forbidden after live commit starts

    1. boot guest with data disk
    2. do live commit
    3. during commit, do snapshot related actions, as live snapshot, resize
       and so on,
    """

    block_test = BlockdevCommitForbiddenActions(test, params, env)
    block_test.run_test()
