from avocado import fail_on
from avocado.utils import process
from virttest import data_dir, utils_misc
from virttest.qemu_storage import QemuImg

from provider import qemu_img_utils as img_utils


def run(test, params, env):
    """
    Check data integrity after qemu unexpectedly quit
    1. Backup the guest image before testing
    2. Convert to a target image with lazy_refcounts=on
    3. Bootup a guest from the target file
    4. Create temporary file in the guest and get md5 value of the temporary file
    5. Kill qemu process after finishing writing data in the guest
    6. Check the target image file
    7. Boot the guest again, check the md5 value of the temporary file
       Make sure the values are the same
    8. Restore the guest image

    :param test: VT test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def kill_vm_process(vm):
        """kill vm process

        :param vm: vm object
        """
        pid = vm.process.get_pid()
        test.log.debug("Ending VM %s process (killing PID %s)", vm.name, pid)
        try:
            utils_misc.kill_process_tree(pid, 9, timeout=60)
            test.log.debug("VM %s down (process killed)", vm.name)
        except RuntimeError:
            test.error("VM %s (PID %s) is a zombie!" % (vm.name, vm.process.get_pid()))

    src_image = params["convert_source"]
    tgt_image = params["convert_target"]
    img_dir = data_dir.get_data_dir()

    # Convert the source image to target
    source = QemuImg(params.object_params(src_image), img_dir, src_image)
    target = QemuImg(params.object_params(tgt_image), img_dir, tgt_image)
    fail_on((process.CmdError,))(source.convert)(source.params, img_dir)

    # Boot a guest from the target file and create a temporary file and kill it
    vm = img_utils.boot_vm_with_images(test, params, env, (tgt_image,))
    session = vm.wait_for_login()
    guest_temp_file = params["guest_temp_file"]
    md5sum_bin = params.get("md5sum_bin", "md5sum")
    sync_bin = params.get("sync_bin", "sync")
    test.log.debug("Create temporary file on guest: %s", guest_temp_file)
    img_utils.save_random_file_to_vm(vm, guest_temp_file, 2048 * 512, sync_bin)
    test.log.debug("Get md5 value of the temporary file")
    md5_value = img_utils.check_md5sum(guest_temp_file, md5sum_bin, session)
    session.close()
    kill_vm_process(vm)

    # Repair the image
    res = target.check(params, img_dir, check_repair="all")
    if res.exit_status != 0:
        test.fail("Repair the image failed, check please.")

    # Boot again the target image and verify the md5 of the temporary file
    vm = img_utils.boot_vm_with_images(test, params, env, (tgt_image,))
    session = vm.wait_for_login()
    test.log.debug("Verify md5 value of the temporary file")
    img_utils.check_md5sum(
        guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
    )
    session.cmd(params["rm_testfile_cmd"] % guest_temp_file)
    session.close()
