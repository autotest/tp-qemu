import logging

from virttest import utils_test
from virttest import utils_misc
from virttest import storage
from virttest import error_context
from virttest import data_dir
from virttest.qemu_storage import QemuImg
from avocado.core import exceptions


class LiveSnapshotBase(object):

    """
    Provide basic functions for live snapshot test cases.
    """

    def __init__(self, params, env):
        """
        Init the default values for live snapshot object.

        :param params: A dict containing VM preprocessing parameters.
        :param env: The environment (a dict-like object).
        """
        self.params = params
        self.env = env
        self.vm = env.get_vm(params["main_vm"])
        self.snapshot_file = params.get("snapshot_file")
        self.snapshot_format = params.get("snapshot_format", "qcow2")
        self.snapshot_mode = params.get("snapshot_mode", "absolute-paths")
        self.node_name = params.get("node_name")
        self.snapshot_node_name = params.get("snapshot_node_name")

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

    def get_base_image(self):
        """
        Get base image.
        """
        base_file = storage.get_image_filename(self.params,
                                               data_dir.get_data_dir())
        return self.vm.get_block({"file": base_file})

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
            error_context.context("Creating an image ...", logging.info)
            self.snapshot_file = self.create_image()
        else:
            self.snapshot_file = self.get_snapshot_file()
        device = self.get_base_image()
        snapshot_args = {"format": self.snapshot_format,
                         "mode": self.snapshot_mode}
        if self.node_name:
            snapshot_args.update({"node-name": self.node_name})
        if self.snapshot_node_name:
            snapshot_args.update({"snapshot-node-name": self.snapshot_node_name})
        self.vm.monitor.live_snapshot(device, self.snapshot_file,
                                      **snapshot_args)

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


@error_context.context_aware
def run(test, params, env):
    vm = env.get_vm(params["main_vm"])

    image_tag = params.get("image_name", "image1")
    image_params = params.object_params(image_tag)
    snapshot_test = LiveSnapshotBase(image_params, env)

    error_context.context("Creating snapshot", logging.info)
    snapshot_test.create_snapshot()
    error_context.context("Checking snapshot created successfully",
                          logging.info)
    snapshot_test.check_snapshot()

    sub_type = params.get("sub_type_after_snapshot")
    if sub_type:
        error_context.context("%s after snapshot" % sub_type, logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    if vm.is_alive():
        vm.destroy()
