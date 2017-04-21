import logging

from autotest.client.shared import error

from virttest import utils_misc

from qemu.tests import block_copy


class BlockStream(block_copy.BlockCopy):

    """
    base class for block stream tests;
    """

    def __init__(self, test, params, env, tag):
        super(BlockStream, self).__init__(test, params, env, tag)

    def parser_test_args(self):
        default_params = {"wait_finished": "yes",
                          "snapshot_format": "qcow2",
                          "snapshot_chain": ""}
        self.default_params.update(default_params)
        return super(BlockStream, self).parser_test_args()

    @error.context_aware
    def start(self):
        """
        start block device streaming job;
        """
        params = self.parser_test_args()
        base_image = params.get("base_image")
        default_speed = params.get("default_speed")

        error.context("start to stream block device", logging.info)
        self.vm.block_stream(self.device.split(' ')[0], default_speed, base_image)
        status = self.get_status()
        if not status:
            raise error.TestFail("no active job found")
        msg = "block stream job running, "
        msg += "with limited speed %s B/s" % default_speed
        logging.info(msg)

    @error.context_aware
    def create_snapshots(self):
        """
        create live snapshot_chain, snapshots chain define in $snapshot_chain
        """
        params = self.parser_test_args()
        image_format = params["snapshot_format"]
        snapshots = params["snapshot_chain"].split()
        error.context("create live snapshots", logging.info)
        for snapshot in snapshots:
            snapshot = utils_misc.get_path(self.data_dir, snapshot)
            image_file = self.get_image_file()
            device = self.vm.live_snapshot(image_file, snapshot, image_format)
            if device != self.device:
                image_file = self.get_image_file()
                logging.info("expect file: %s" % snapshot +
                             "opening file: %s" % image_file)
                raise error.TestFail("create snapshot '%s' fail" % snapshot)
            self.trash_files.append(snapshot)

    def action_when_streaming(self):
        """
        run steps when job in steaming;
        """
        return self.do_steps("when_streaming")
