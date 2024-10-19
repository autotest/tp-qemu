from provider import blockdev_stream_nowait, job_utils


class BlkdevStreamFilterNode(blockdev_stream_nowait.BlockdevStreamNowaitTest):
    """
    blockdev-stream filter node name test
    """

    def _init_stream_options(self):
        super(BlkdevStreamFilterNode, self)._init_stream_options()
        filter_node_name = self.params["filter_node_name"]
        if filter_node_name:
            self._stream_options["filter-node-name"] = filter_node_name

    def check_filter_nodes_name(self, during_stream=True):
        """
        Check filter node name set during stream
        """
        blocks_info = self.main_vm.monitor.query("block")
        if during_stream:
            for block in blocks_info:
                block_node_name = block["inserted"].get("node-name")
                if (
                    self.params.get("source_images") in block["qdev"]
                    and block_node_name == self.params["filter_node_name"]
                ):
                    break
            else:
                self.test.fail(
                    "Filter node name '%s' is not set as expected"
                    "during stream" % self.params["filter_node_name"]
                )
        else:
            for block in blocks_info:
                block_node_name = block["inserted"].get("node-name")
                if (
                    self.params.get("source_images") in block["qdev"]
                    and block_node_name != self.params["filter_node_name"]
                ):
                    break
            else:
                self.test.fail(
                    "Filter node name '%s' set after stream"
                    % self.params["filter_node_name"]
                )

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        job_utils.check_block_jobs_started(
            self.main_vm,
            [self._job],
            self.params.get_numeric("job_started_timeout", 60),
        )
        self.check_filter_nodes_name()
        self.wait_stream_job_completed()
        self.check_filter_nodes_name(during_stream=False)


def run(test, params, env):
    """
    blockdev-stream speed test

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a snapshot image for data image
        5. take snapshot on data image
        6. do blockdev-stream with filter-node-name set
        7. check nodes info
        8. wait till stream job completed

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    filter_node_name = BlkdevStreamFilterNode(test, params, env)
    filter_node_name.run_test()
