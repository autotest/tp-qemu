import os
import logging

from autotest.client.shared import error, utils

from virttest import utils_misc
from virttest import storage
from virttest import qemu_storage
from virttest import nfs

from qemu.tests import block_copy


class DriveMirror(block_copy.BlockCopy):

    """
    base class for block mirror tests;
    """

    def __init__(self, test, params, env, tag):
        super(DriveMirror, self).__init__(test, params, env, tag)
        self.target_image = self.get_target_image()

    def parser_test_args(self):
        """
        paraser test args and set default value;
        """
        default_params = {"create_mode": "absolute-path",
                          "reopen_timeout": 60,
                          "full_copy": "full",
                          "check_event": "no"}
        self.default_params.update(default_params)
        params = super(DriveMirror, self).parser_test_args()
        if params["block_mirror_cmd"].startswith("__"):
            params["full_copy"] = (params["full_copy"] == "full")
        params = params.object_params(params["target_image"])
        if params.get("image_type") == "iscsi":
            params.setdefault("host_setup_flag", 2)
            params["host_setup_flag"] = int(params["host_setup_flag"])
        return params

    def get_target_image(self):
        params = self.parser_test_args()
        target_image = storage.get_image_filename(params, self.data_dir)
        if params.get("image_type") == "nfs":
            image = nfs.Nfs(params)
            image.setup()
            utils_misc.wait_for(lambda: os.path.ismount(image.mount_dir),
                                timeout=30)
        elif params.get("image_type") == "iscsi":
            image = qemu_storage.Iscsidev(params, self.data_dir,
                                          params["target_image"])
            return image.setup()

        if (params["create_mode"] == "existing" and
                not os.path.exists(target_image)):
            image = qemu_storage.QemuImg(params, self.data_dir,
                                         params["target_image"])
            image.create(params)

        return target_image

    def get_device(self):
        params = super(DriveMirror, self).parser_test_args()
        image_file = storage.get_image_filename(params, self.data_dir)
        return self.vm.get_block({"file": image_file})

    @error.context_aware
    def check_granularity(self):
        """
        Check granularity value as set.
        """
        device_id = self.get_device()
        info = self.vm.monitor.info_block().get(device_id)
        if "granularity" in self.params:
            target_gran = int(self.params["granularity"])
            dirty_bitmap = info.get("dirty-bitmaps", "0")
            granularity = int(dirty_bitmap[0].get("granularity", "0"))
            if granularity != target_gran:
                raise error.TestFail(
                    "Granularity unmatched. Target is %d, result is %d" %
                    (target_gran, granularity))

    @error.context_aware
    def check_node_name(self):
        """
        Check node name as set, after block job complete.
        """
        device_id = self.vm.get_block({"file": self.target_image})
        info = self.vm.monitor.info_block().get(device_id)
        if "node_name" in self.params:
            node_name_exp = self.params["node_name"]
            node_name = info.get("node-name", "")
            if node_name != node_name_exp:
                raise error.TestFail(
                    "node-name is: %s, while set value is: %s" %
                    (node_name, node_name_exp))

    @error.context_aware
    def start(self):
        """
        start block device mirroring job;
        """
        params = self.parser_test_args()
        target_image = self.target_image
        device = self.device
        default_speed = params["default_speed"]
        target_format = params["image_format"]
        create_mode = params["create_mode"]
        full_copy = params["full_copy"]
        args = {"mode": create_mode, "speed": default_speed,
                "format": target_format}
        if 'granularity' and 'buf_count' in params:
            granularity = int(params["granularity"])
            buf_size = granularity * int(params["buf_count"])
            args.update({"granularity": granularity,
                         "buf-size": buf_size})
        if 'node_name' in params:
            args.update({"node-name": params.get("node_name")})
        error.context("Start to mirror block device", logging.info)
        self.vm.block_mirror(device, target_image, full_copy,
                             **args)
        if not self.get_status():
            raise error.TestFail("No active mirroring job found")
        if params.get("image_type") != "iscsi":
            self.trash_files.append(target_image)

    @error.context_aware
    def reopen(self):
        """
        reopen target image, then check if image file of the device is
        target images;
        """
        params = self.parser_test_args()
        target_format = params["image_format"]
        timeout = params["reopen_timeout"]
        error.context("reopen new target image", logging.info)
        if self.vm.monitor.protocol == "qmp":
            self.vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
        self.vm.block_reopen(self.device, self.target_image, target_format)
        self.wait_for_finished()

    def action_after_reopen(self):
        """
        run steps after reopened new target image;
        """
        return self.do_steps("after_reopen")

    def clean(self):
        super(DriveMirror, self).clean()
        params = self.parser_test_args()
        if params.get("image_type") == "iscsi":
            params["host_setup_flag"] = int(params["host_setup_flag"])
            qemu_img = utils_misc.get_qemu_img_binary(self.params)
            # Reformat it to avoid impact other test
            cmd = "%s create -f %s %s %s" % (qemu_img,
                                             params["image_format"],
                                             self.target_image,
                                             params["image_size"])
            utils.system(cmd)
            image = qemu_storage.Iscsidev(params, self.data_dir,
                                          params["target_image"])
            image.cleanup()
        elif params.get("image_type") == "nfs":
            image = nfs.Nfs(params)
            image.cleanup()


def run(test, params, env):
    pass
