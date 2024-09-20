from avocado import fail_on
from avocado.utils import process
from virttest import data_dir
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Check the data after resizing short overlay over longer backing files.
    1. Create a qcow2 base image.
    2. Create a middle snapshot file with smaller size.
    3. Create a top snapshot with the size as the same as the one of base.
    4. Write '1' to the base image file.
    5. Check the data of the top image file.
    6. Commit top image file.
    7. Check the data in the middle image file.
    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError as err:
            test.fail("qemu-io to '%s' failed: %s." % (img.image_filename, err))

    images = params["image_chain"].split()
    root_dir = data_dir.get_data_dir()
    base = QemuImg(params.object_params(images[0]), root_dir, images[0])
    mid = QemuImg(params.object_params(images[1]), root_dir, images[1])
    top = QemuImg(params.object_params(images[-1]), root_dir, images[-1])

    test.log.info("Create base and snapshot files")
    for image in (base, mid, top):
        image.create(image.params)

    _qemu_io(base, params["base_cmd"])

    top_cmd = params["top_cmd"]
    _qemu_io(top, top_cmd)

    test.log.info("Commit %s image file.", top.image_filename)
    fail_on((process.CmdError,))(top.commit)()

    _qemu_io(mid, top_cmd)
