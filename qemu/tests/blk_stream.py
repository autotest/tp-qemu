import logging

from virttest import error_context

from qemu.tests import block_copy


class BlockStream(block_copy.BlockCopy):

    """
    base class for block stream tests;
    """

    def __init__(self, test, params, env, tag):
        super(BlockStream, self).__init__(test, params, env, tag)
        self.base_image = None
        self.ext_args = {}

    def parser_test_args(self):
        default_params = {"wait_finished": "yes",
                          "snapshot_format": "qcow2",
                          "snapshot_chain": ""}
        self.default_params.update(default_params)
        return super(BlockStream, self).parser_test_args()

    @error_context.context_aware
    def start(self):
        """
        start block device streaming job;
        """
        params = self.parser_test_args()
        if params.get("default_speed"):
            self.ext_args["speed"] = int(params["default_speed"])
        if self.base_image:
            self.ext_args["base"] = self.base_image
        elif params.get("base_node"):
            self.ext_args["base-node"] = params["base_node"]
        if params.get("backing_file"):
            self.ext_args["backing-file"] = params["backing_file"]
        error_context.context("start to stream block device", logging.info)
        self.job_id = self.vm.block_stream(self.device, **self.ext_args)

    def action_when_streaming(self):
        """
        run steps when job in steaming;
        """
        return self.do_steps("when_streaming")
