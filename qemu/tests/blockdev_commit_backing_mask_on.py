from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockDevCommitBackingMaskOn(BlockDevCommitTest):
    def commit_snapshots(self):
        self.base_device = self.params["device_tag"].split()[0]
        device_params = self.params.object_params(self.base_device)
        snapshot_tags = device_params["snapshot_tags"].split()
        self.device_node = self.get_node_name(self.base_device)
        options = ["base-node", "top-node", "backing-mask-protocol"]
        arguments = self.params.copy_from_keys(options)
        arguments["base-node"] = self.device_node
        arguments["top-node"] = self.get_node_name(snapshot_tags[-2])
        arguments["backing-mask-protocol"] = self.params.get("backing_mask_protocol")
        device = self.get_node_name(snapshot_tags[-1])
        backup_utils.block_commit(self.main_vm, device, **arguments)

    def check_backing_format(self):
        base_image = self.get_image_by_tag(self.base_device)
        base_format = base_image.get_format()
        output = self.snapshot_images[-1].info(force_share=True).split("\n")
        for item in output:
            if "backing file format" in item:
                if base_format not in item:
                    self.test.fail(
                        "Expected format: %s, current format: %s"
                        % (item.split(":")[1], base_format)
                    )

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.verify_data_file()
            self.check_backing_format()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    6. verify files's md5
    """

    block_test = BlockDevCommitBackingMaskOn(test, params, env)
    block_test.run_test()
