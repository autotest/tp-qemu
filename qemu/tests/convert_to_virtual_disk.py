from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Convert a image to a virtual block device.
    1. Create source and middle images.
    2. Setup loop device with the middle image.
    3. Convert the source image to the loop device.
    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def setup_loop_dev(image_path):
        """
        Setup a loop device with a file image.
        :param image_path: The path to the image used to setup loop device
        :return: The loop device under /dev
        """
        cmd_result = process.run("losetup -f %s --show" % image_path)
        return cmd_result.stdout_text.strip()

    def free_loop_dev(loop_dev):
        """
        Free a loop device.
        :param loop_dev: The loop device will be free
        """
        process.run("losetup -d %s" % loop_dev)

    src_img = params["images"].split()[0]
    mid_img = params["images"].split()[-1]
    root_dir = data_dir.get_data_dir()
    source = QemuImg(params.object_params(src_img), root_dir, src_img)
    middle = QemuImg(params.object_params(mid_img), root_dir, mid_img)
    mid_filename = middle.image_filename

    test.log.info("Create the test image files.")
    source.create(source.params)
    middle.create(middle.params)

    test.log.info("Setup target loop device via 'losetup'.")
    target = setup_loop_dev(mid_filename)
    params["image_name_target"] = target

    test.log.debug(
        "Convert from %s to %s with cache mode none.",
        source.image_filename,
        mid_filename,
    )
    try:
        fail_on((process.CmdError,))(source.convert)(
            params.object_params(src_img), root_dir, cache_mode="none"
        )
    finally:
        test.log.info("Clean the loop device.")
        free_loop_dev(target)
