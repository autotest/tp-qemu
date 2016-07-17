import logging

from virttest import utils_misc
from virttest import data_dir
from virttest.qemu_storage import QemuImg
from avocado.core import exceptions
from qemu.tests import block_copy


class LiveSnapshot(block_copy.BlockCopy):

    """
    Provide basic functions for live snapshot test cases.
    """

    def __init__(self, test, params, env, tag):
        """
        Init the default values for live snapshot object.

        :param params: A dict containing VM preprocessing parameters.
        :param env: The environment (a dict-like object).
        """
        super(LiveSnapshot, self).__init__(test, params, env, tag)
        self.default_params = {"login_timeout": 360}
        self.snapshot_file = self.params.get("snapshot_file")
        self.node_name = self.params.get("node_name")
        self.snapshot_node_name = self.params.get("snapshot_node_name")
        self.snapshot_mode = params.get("snapshot_mode", "absolute-paths")
        self.snapshot_format = params.get("snapshot_format", "qcow2")
        self.snapshot_args = {"mode": self.snapshot_mode,
                              "format": self.snapshot_format}
        if self.node_name:
            self.snapshot_args.update({"node-name": self.node_name})
        if self.snapshot_node_name:
            self.snapshot_args.update({"snapshot-node-name": self.snapshot_node_name})

    def create_image(self):
        """
        Create a image.
        """
        image_name = self.params.get("image_name")
        self.params['image_name_snapshot'] = image_name + "-snap"
        snapshot_params = self.params.object_params("snapshot")
        base_dir = self.params.get("images_base_dir", data_dir.get_data_dir())

        image_io = QemuImg(snapshot_params, base_dir, image_name)
        image_name, _ = image_io.create(snapshot_params)
        return image_name

    def get_snapshot_file(self):
        """
        Get path of snapshot file.
        """
        snapshot_file = "images/%s" % self.snapshot_file
        return utils_misc.get_path(data_dir.get_data_dir(), snapshot_file)

    def create_snapshot(self):
        """
        Create a live disk snapshot.
        """
        if self.snapshot_mode == "existing":
            logging.info("Creating an image ...")
            self.snapshot_file = self.create_image()
        else:
            self.snapshot_file = self.get_snapshot_file()
        logging.info("Creating snapshot")
        self.vm.monitor.live_snapshot(self.device, self.snapshot_file,
                                      **self.snapshot_args)
        logging.info("Checking snapshot created successfully")
        self.check_snapshot()

    def check_snapshot(self):
        """
        Check whether the snapshot is created successfully.
        """
        snapshot_info = str(self.vm.monitor.info("block"))
        if self.snapshot_file not in snapshot_info:
            logging.error(snapshot_info)
            raise exceptions.TestFail("Snapshot doesn't exist")
        if self.snapshot_node_name:
            match_string = "u'node-name': u'%s'" % self.snapshot_node_name
            if match_string not in snapshot_info:
                logging.error(snapshot_info)
                raise exceptions.TestFail("Can not find node name %s of"
                                          " snapshot in block info %s"
                                          % (self.snapshot_node_name,
                                             snapshot_info))

    def action_after_finished(self):
        """
        Run steps after live snapshot done.
        """
        return self.do_steps("after_finished")
