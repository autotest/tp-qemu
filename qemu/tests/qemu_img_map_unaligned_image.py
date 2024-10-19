import json
import random
import string

from avocado.utils import process
from virttest import data_dir, utils_misc, utils_qemu
from virttest.qemu_storage import QemuImg
from virttest.utils_version import VersionInterval


def run(test, params, env):
    """
    qemu-img map an unaligned image.

    1.create a raw file using truncate
    2.write data into the raw file
    3.verify the dumped mete-data using qemu-img map

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def _generate_random_string(max_len=19):
        """Generate random alphabets string in the range of [1, max_len+1]."""
        random_str = "".join(
            random.choice(string.ascii_lowercase)
            for _ in range(random.randint(1, max_len))
        )
        return random_str, len(random_str)

    def _verify_qemu_img_map(output, str_len):
        """Verify qemu-img map's output."""
        test.log.info("Verify the dumped mete-data of the unaligned image.")
        qemu_binary = utils_misc.get_qemu_binary(params)
        qemu_version = utils_qemu.get_qemu_version(qemu_binary)[0]
        if qemu_version in VersionInterval("[8.2.0,)"):
            expected = [
                {
                    "start": 0,
                    "length": str_len,
                    "depth": 0,
                    "present": True,
                    "zero": False,
                    "data": True,
                    "compressed": False,
                    "offset": 0,
                },
                {
                    "start": str_len,
                    "length": 512 - (str_len % 512),
                    "depth": 0,
                    "present": True,
                    "zero": True,
                    "data": False,
                    "compressed": False,
                    "offset": str_len,
                },
            ]
        elif qemu_version in VersionInterval("[6.1.0,)"):
            expected = [
                {
                    "start": 0,
                    "length": str_len,
                    "depth": 0,
                    "present": True,
                    "zero": False,
                    "data": True,
                    "offset": 0,
                },
                {
                    "start": str_len,
                    "length": 512 - (str_len % 512),
                    "depth": 0,
                    "present": True,
                    "zero": True,
                    "data": False,
                    "offset": str_len,
                },
            ]
        else:
            expected = [
                {
                    "start": 0,
                    "length": str_len,
                    "depth": 0,
                    "zero": False,
                    "data": True,
                    "offset": 0,
                },
                {
                    "start": str_len,
                    "length": 512 - (str_len % 512),
                    "depth": 0,
                    "zero": True,
                    "data": False,
                    "offset": str_len,
                },
            ]
        res = json.loads(output)
        if res != expected:
            test.fail(
                "The dumped mete-data of the unaligned "
                "image '%s' is not correct." % img.image_filename
            )

    img_param = params.object_params("test")
    img = QemuImg(img_param, data_dir.get_data_dir(), "test")

    test.log.info("Create a new file %s using truncate.", img.image_filename)
    process.run("rm -f %s" % img.image_filename)
    process.run("truncate -s 1G %s " % img.image_filename)

    random_str, str_len = _generate_random_string()
    test.log.info("Write '%s' into the file %s.", random_str, img.image_filename)
    process.run("echo -n '%s' > %s" % (random_str, img.image_filename), shell=True)
    res = img.map(output="json")
    if res.exit_status != 0:
        test.fail("qemu-img map error: %s." % res.stderr_text)
    _verify_qemu_img_map(res.stdout_text, str_len)
