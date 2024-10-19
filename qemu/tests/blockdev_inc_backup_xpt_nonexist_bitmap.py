import logging
import os
import string

from avocado.utils import process
from virttest import utils_misc

from provider.blockdev_base import BlockdevBaseTest
from provider.nbd_image_export import QemuNBDExportImage

LOG_JOB = logging.getLogger("avocado.test")


class BlkdevIncXptNonexistBitmap(BlockdevBaseTest):
    def __init__(self, test, params, env):
        super(BlkdevIncXptNonexistBitmap, self).__init__(test, params, env)
        self.source_images = []
        self.nbd_exports = []
        self.bitmaps = []
        self.src_img_tags = params.objects("source_images")
        list(map(self._init_arguments_by_params, self.src_img_tags))

    def _init_arguments_by_params(self, tag):
        image_params = self.params.object_params(tag)
        self.source_images.append("drive_%s" % tag)
        self.bitmaps.append("bitmap_%s" % tag)
        image_params["nbd_export_bitmaps"] = "bitmap_%s" % tag
        self.nbd_exports.append(QemuNBDExportImage(image_params, tag))

    def expose_nonexist_bitmap(self):
        def _nbd_expose_cmd(qemu_nbd, filename, local_image, params):
            cmd_dict = {
                "export_format": "",
                "persistent": "-t",
                "port": "",
                "filename": "",
                "fork": "--fork",
                "pid_file": "",
                "bitmap": "",
            }
            export_cmd = (
                "{export_format} {persistent} {port} {bitmap} "
                "{fork} {pid_file} {filename}"
            )
            pid_file = utils_misc.generate_tmp_file_name(
                "%s_nbd_server" % local_image, "pid"
            )
            cmd_dict["pid_file"] = "--pid-file %s" % pid_file
            cmd_dict["filename"] = filename
            if params.get("nbd_export_format"):
                cmd_dict["export_format"] = "-f %s" % params["nbd_export_format"]
            else:
                if params.get("nbd_port"):
                    cmd_dict["port"] = "-p %s" % params["nbd_port"]
            if params.get("nbd_export_bitmaps"):
                cmd_dict["bitmap"] = "".join(
                    [" -B %s" % _ for _ in params["nbd_export_bitmaps"].split()]
                )
            cmdline = qemu_nbd + " " + string.Formatter().format(export_cmd, **cmd_dict)
            return pid_file, cmdline

        LOG_JOB.info("Export inconsistent bitmap with qemu-nbd")
        pid_file, cmd = _nbd_expose_cmd(
            self.nbd_exports[0]._qemu_nbd,
            self.nbd_exports[0]._local_filename,
            self.nbd_exports[0]._tag,
            self.nbd_exports[0]._image_params,
        )
        result = process.run(
            cmd, ignore_status=True, shell=True, ignore_bg_processes=True
        )
        if result.exit_status == 0:
            with open(pid_file, "r") as pid_file_fd:
                qemu_nbd_pid = int(pid_file_fd.read().strip())
            os.unlink(pid_file)
            utils_misc.kill_process_tree(qemu_nbd_pid, 9, timeout=60)
            self.test.fail("Can expose image with a non-exist bitmap")

        error_msg = self.params.get("error_msg") % self.bitmaps[0]
        if error_msg not in result.stderr.decode():
            self.test.fail(result.stderr.decode())

    def run_test(self):
        self.expose_nonexist_bitmap()


def run(test, params, env):
    """
    Expose non-exist bitmaps via qemu-nbd

    test steps:
        1. create a 2G disk image
        2. expose the disk image with a nonexist bitmap

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    expose_nonexist_bitmap = BlkdevIncXptNonexistBitmap(test, params, env)
    expose_nonexist_bitmap.run_test()
