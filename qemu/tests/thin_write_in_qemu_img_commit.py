import json
import re

from virttest import data_dir, env_process, utils_misc, utils_numeric
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg
from virttest.utils_version import VersionInterval

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


def run(test, params, env):
    """
    Check thin write in qemu-img commit.

    1) write 0x1 into the entire base image through qemu-io
    2) create a external snapshot sn of the base
    3) write specific length zeros at the beginning of the snapshot
    4) commit sn back to base
    5) make sure the zeros have been committed into the base image

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_image_object(tag):
        """Get QemuImg object by tag."""
        img_param = params.object_params(tag)
        return QemuImg(img_param, img_root_dir, tag)

    def _create_external_snapshot(tag):
        """Create an external snapshot based on tag."""
        test.log.info("Create external snapshot %s.", tag)
        qit = QemuImgTest(test, params, env, snapshot)
        qit.create_snapshot()

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        q = QemuIOSystem(test, params, img.image_filename)
        q.cmd_output(cmd, 120)

    def _verify_map_output(output):
        """ "Verify qemu map output."""
        qemu_path = utils_misc.get_qemu_binary(params)
        qemu_version = env_process._get_qemu_version(qemu_path)
        match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+(\-[0-9]+)?", qemu_version)
        host_qemu = match.group(0)
        expected = {
            "length": int(utils_numeric.normalize_data_size(params["write_size"], "B")),
            "start": 0,
            "depth": 0,
            "zero": True,
            "data": False,
        }
        if host_qemu in VersionInterval("[6.1.0,)"):
            expected["present"] = True
        if host_qemu in VersionInterval("[8.2.0,)"):
            expected["compressed"] = False
        if expected not in json.loads(output.stdout_text):
            test.fail(
                "Commit failed, data from 0 to %s are not zero" % params["write_size"]
            )

    gen = generate_base_snapshot_pair(params["image_chain"])
    img_root_dir = data_dir.get_data_dir()
    base, snapshot = next(gen)

    img_base = _get_image_object(base)
    _qemu_io(img_base, "write -P 1 0 %s" % params["image_size_base"])

    _create_external_snapshot(snapshot)
    img_sn = _get_image_object(snapshot)
    _qemu_io(img_sn, "write -z 0 %s" % params["write_size"])

    img_sn.commit()
    _verify_map_output(img_base.map(output="json"))
