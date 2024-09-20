import time

from virttest import data_dir, utils_misc
from virttest.qemu_storage import QemuImg

from provider import qemu_img_utils as img_utils
from provider.storage_benchmark import generate_instance


def run(test, params, env):
    """
    Check data integrity after qemu unexpectedly quit
    1. Backup the guest image before testing
    2. Boot a guest
    3. If tmp_file_check == yes
    3.1 Create temporary file in the guest
    3.2 Get md5 value of the temporary file
    4. Kill qemu process after finishing writing data in the guest
    5. Boot the guest again, check the md5 value of the temporary file
       Make sure the values are the same
    6. If tmp_file_check == no
    6.1 Kill qemu process during writing data in the guest
    7. Boot the guest again, make sure it could boot successfully
    8. Check the testing image and repair the leaked clusters
    9. Restore the guest image

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

    def run_iozone_background(vm):
        """
        run iozone in guest

        :param vm: vm object
        """
        test.log.debug("Start iozone in background.")
        iozone = generate_instance(params, vm, "iozone")
        args = (params["iozone_cmd_opitons"], int(params["iozone_timeout"]))
        iozone_thread = utils_misc.InterruptedThread(iozone.run, args)
        iozone_thread.start()
        if not utils_misc.wait_for(lambda: iozone_thread.is_alive, 60):
            test.error("Failed to start iozone thread.")
        return iozone_thread

    vm = img_utils.boot_vm_with_images(test, params, env)
    tmp_file_check = params.get_boolean("tmp_file_check")
    if tmp_file_check:
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
        vm = img_utils.boot_vm_with_images(test, params, env)
        session = vm.wait_for_login()
        test.log.debug("Verify md5 value of the temporary file")
        img_utils.check_md5sum(
            guest_temp_file, md5sum_bin, session, md5_value_to_check=md5_value
        )
        session.cmd(params["rm_testfile_cmd"] % guest_temp_file)
    else:
        iozone_testfile = params["iozone_testfile"]
        iozone_thread = run_iozone_background(vm)
        running_time = params.get_numeric("running_time", 15)
        time.sleep(running_time)
        if iozone_thread.is_alive:
            kill_vm_process(vm)
        else:
            test.error("Iozone thread is not running.")
        vm = img_utils.boot_vm_with_images(test, params, env)
        session = vm.wait_for_login()
        session.cmd(params["rm_testfile_cmd"] % iozone_testfile)
    session.close()
    vm.destroy()

    # Check the testing image and repair the leaked clusters
    root_dir = data_dir.get_data_dir()
    img = params.objects("images")[0]
    img_param = params.object_params(img)
    img = QemuImg(img_param, root_dir, img)
    res = img.check(params, root_dir)
    if res.exit_status == 2:
        test.fail("Image is corrupted, check please.")
    elif res.exit_status == 3:
        test.log.info("Leaked clusters found in the image, repair them now.")
        res = img.check(params, root_dir, check_repair="leaks")
        if res.exit_status != 0:
            test.fail("Repair the leaked image failed, check please.")
        # Boot guest again to double check the image works fine
        vm = img_utils.boot_vm_with_images(test, params, env)
        vm.wait_for_login()
