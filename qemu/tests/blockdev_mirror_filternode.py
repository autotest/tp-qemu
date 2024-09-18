from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorFilterNodeTest(BlockdevMirrorNowaitTest):
    """
    Block mirror with filter-node-name set test
    """

    def __init__(self, test, params, env):
        params["filter-node-name"] = params["filter_node_name"]
        super(BlockdevMirrorFilterNodeTest, self).__init__(test, params, env)

    def check_filter_node_name(self):
        """The filter node name should be set when doing mirror"""
        for item in self.main_vm.monitor.query("block"):
            if (
                self._source_images[0] in item["qdev"]
                and item["inserted"].get("node-name") == self.params["filter-node-name"]
            ):
                break
        else:
            self.test.fail(
                "Filter node name(%s) is not set when doing mirror"
                % self.params["filter-node-name"]
            )

    def do_test(self):
        self.blockdev_mirror()
        self.check_block_jobs_started(
            self._jobs, self.params.get_numeric("mirror_started_timeout", 5)
        )
        self.check_filter_node_name()
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
     Block mirror with filter-node-name test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a target disk for mirror to VM via qmp commands
        5. do block-mirror with filter node set
        6. check filter node name is set when doing mirror
        7. complete the mirror job
        8. check the mirror disk is attached
        9. restart vm with the mirror disk as its data disk
       10. check the file's md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorFilterNodeTest(test, params, env)
    mirror_test.run_test()
