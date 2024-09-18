from avocado.utils import process
from virttest.data_dir import get_data_dir
from virttest.lvm import EmulatedLVM
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    Commit with multiple bitmaps to a non-enough space source.
    Steps:
        1) Create lvm
        2) Create base image on lvm
        3) Add 8 bitmaps to base
        4) Create a snapshot image
        5) Add a bitmap to snapshot image
        6) Fullwrite snapshot image
        7) Commit snapshot to base, commit should
           fail with error

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _image_create(image_name):
        """Create an image."""
        img_param = params.object_params(image_name)
        img = QemuImg(img_param, get_data_dir(), image_name)
        img.create(img_param)
        return img

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        try:
            QemuIOSystem(test, params, img.image_filename).cmd_output(cmd, 120)
        except process.CmdError as err:
            test.fail("qemu-io to '%s' failed: %s." % (img.image_filename, str(err)))

    def _clean_images(img_list):
        """Remove images from image_list."""
        for img in img_list:
            img.remove()

    try:
        lvm = EmulatedLVM(params, get_data_dir())
        lvm.setup()
        images_list = []
        base, top = params.get("image_chain").split()
        base_image = _image_create(base)
        images_list.append(base_image)
        test.log.info("Add multiple bitmaps to base image.")
        bitmap_nums_base = params["bitmap_nums_base"]
        for num in range(0, int(bitmap_nums_base)):
            bitmap_name = params.get("bitmap_name_base") % num
            base_image.bitmap_add(bitmap_name)
        top_image = _image_create(top)
        images_list.append(top_image)
        top_image.bitmap_add(params.get("bitmap_name_top"))
        _qemu_io(top_image, params["top_io_cmd"])
        try:
            top_image.commit(params.get("cache_mode"), base=base)
        except process.CmdError as err:
            err_msg = err.result.stderr.decode()
            err_msg_cfg = params.get("error_msg").split(",")
            if not all(msg in err_msg for msg in err_msg_cfg):
                test.fail("Not all expected error msg are caught here")
        else:
            test.fail("Commit with success unexpectedly")
    finally:
        _clean_images(images_list)
        lvm.cleanup()
