from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage, utils_misc, utils_test

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    1) Convert remote readonly system image to the local image
    2) Start VM from the local image,
       with the remote iso image as its cdrom
    3) Log into VM
    4) Check readable cdrom
    """

    def _convert_image():
        source = params["images"].split()[0]
        target = params["convert_target"]
        source_params = params.object_params(source)
        target_params = params.object_params(target)
        source_image = qemu_storage.QemuImg(source_params, None, source)

        # Convert source to target
        fail_on((process.CmdError,))(source_image.convert)(
            target_params, data_dir.get_data_dir()
        )

    _convert_image()
    vm = img_utils.boot_vm_with_images(test, params, env, (params["convert_target"],))
    session = vm.wait_for_login(timeout=params.get_numeric("login_timeout", 360))
    cdroms = utils_misc.wait_for(
        lambda: (utils_test.get_readable_cdroms(params, session)),
        timeout=params.get_numeric("timeout", 10),
    )
    session.close()
    if not cdroms:
        test.fail("None readable cdrom found in vm.")
