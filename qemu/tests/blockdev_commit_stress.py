from virttest import utils_test

from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitStress(BlockDevCommitTest):
    def run_stress_test(self):
        self.stress_test = utils_test.VMStress(self.main_vm, "stress", self.params)
        self.stress_test.load_stress_tool()

    def stress_running_check(self):
        if not self.stress_test.app_running():
            self.test.fail("Stress app does not running as expected")

    def pre_test(self):
        if not self.main_vm.is_alive():
            self.main_vm.create()
        self.main_vm.verify_alive()
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            self.configure_disk(device)
            self.run_stress_test()
            self.prepare_snapshot_file(snapshot_tags)
            self.create_snapshots(snapshot_tags, device)

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.stress_running_check()
            self.verify_data_file()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with system disk
    2. run stress test in guest
    3. create 4 snapshots and save file in each snapshot
    4. commit snapshot 3 to base
    5. verify if stress test still running and verify file's md5 after commit
    """

    block_test = BlockdevCommitStress(test, params, env)
    block_test.run_test()
