from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, qemu_storage

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Convert image with parameter -r, rate limit: the unit is bytes per second.
    1. Boot a guest
    2. Create temporary file in the guest
    3. Get md5 value of the temporary file
    3. Destroy the guest
    4. Convert image to raw/qcow2/luks with parameter -r
    4. Boot the target image, check the md5 value of the temporary file
       Make sure the values are the same

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = img_utils.boot_vm_with_images(test, params, env)
    session = vm.wait_for_login()
    guest_temp_file = params["guest_temp_file"]
    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    test.log.debug("Create temporary file on guest: %s", guest_temp_file)
    img_utils.save_random_file_to_vm(vm, guest_temp_file, 2048 * 512, sync_bin)
    test.log.debug("Get md5 value of the temporary file")
    md5_value = img_utils.check_md5sum(guest_temp_file, md5sum_bin, session)
    session.close()
    vm.destroy()

    root_dir = data_dir.get_data_dir()
    convert_source = params["convert_source"]
    convert_target = params["convert_target"]
    source_params = params.object_params(convert_source)
    target_params = params.object_params(convert_target)
    source = qemu_storage.QemuImg(source_params, root_dir, convert_source)
    target = qemu_storage.QemuImg(target_params, root_dir, convert_target)
    test.log.debug("Convert from %s to %s", convert_source, convert_target)
    fail_on((process.CmdError,))(source.convert)(source_params, root_dir)
    test.log.debug("sync host data after convert")
    process.system("sync")

    vm = img_utils.boot_vm_with_images(test, params, env, (convert_target,))
    session = vm.wait_for_login()
    test.log.debug("Verify md5 value of the temporary file")
    img_utils.check_md5sum(
        guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
    )
    session.close()
    target.remove()
