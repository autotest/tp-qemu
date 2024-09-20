from virttest import data_dir, qemu_storage, storage

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitBackingFile(BlockDevCommitTest):
    def check_backing_file(self):
        if self.main_vm.is_alive():
            self.main_vm.destroy()
        device = self.params["snapshot_tags"].split()[-1]
        device_params = self.params.object_params(device)
        image_obj = qemu_storage.QemuImg(device_params, data_dir.get_data_dir(), device)
        output = image_obj.info()
        self.test.log.info(output)
        if self.backing_file not in output:
            self.test.fail("The backing file info of % is not correct" % device)

    def commit_snapshots(self):
        device = self.params.get("device_tag")
        device_params = self.params.object_params(device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(device)
        options = ["base-node", "top-node", "speed", "backing-file"]
        arguments = self.params.copy_from_keys(options)
        arguments["base-node"] = self.get_node_name(device)
        backing_file = self.params.object_params(snapshot_tags[-2])
        self.backing_file = storage.get_image_filename(
            backing_file, data_dir.get_data_dir()
        )
        arguments["backing-file"] = self.backing_file
        arguments["top-node"] = self.get_node_name(snapshot_tags[-2])
        device = self.get_node_name(snapshot_tags[-1])
        backup_utils.block_commit(self.main_vm, device, **arguments)
        self.main_vm.destroy()

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.check_backing_file()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit "backing-file" option test

    1. boot guest and create 4 snapshots and save file in each snapshot
    2. do block commit and wait for block job completed
    3. check backing-file of sn4
    """

    block_test = BlockdevCommitBackingFile(test, params, env)
    block_test.run_test()
