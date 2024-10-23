from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitToNospace(BlockDevCommitTest):
    def generate_tempfile(self, root_dir, filename="data", size="1000M", timeout=360):
        backup_utils.generate_tempfile(self.main_vm, root_dir, filename, size, timeout)
        self.files_info.append([root_dir, filename])

    def commit_snapshots(self):
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            device = self.get_node_name(snapshot_tags[-1])
            try:
                backup_utils.block_commit(self.main_vm, device)
            except AssertionError as e:
                if self.params["qmp_error_msg"] not in str(e):
                    self.test.fail(str(e))
            else:
                self.test.fail("Commit to non-enough space success")

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit to non-enough space

    1). create small space(less than 1G)
    2). start vm with 2G data disk on it
    3). create snapshot, dd 1G file on it.
    4). commit snapshot to base
    """

    block_test = BlockdevCommitToNospace(test, params, env)
    block_test.run_test()
