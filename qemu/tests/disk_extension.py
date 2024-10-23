from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_disk,
    utils_misc,
    utils_test,
)
from virttest.qemu_storage import QemuImg
from virttest.utils_misc import get_linux_drive_path


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'disk images extension in io-error status' test

    1) Create folder and mounted it as tmpfs type.
    2) Create a raw image file with small size(50M) under the tmpfs folder.
    3) Attach loop device with above raw image file.
    4) Create qcow2 image on the loop device with larger size (500M).
    5) Boot vm with loop device as data disk.
    6) Access  guest vm and execute dd operation on the data disk.
     the IO size is same as the loop device virtual disk size.
    7) Verify vm status is paused status in qmp or hmp.
    8) Continue to increase disk size of the raw image file,
     and update the loop device.
    9) Verify vm status whether in expected status:
      if the raw image file size is smaller than loop device virtual disk size,
      it is in paused status,Otherwise it is in running status.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def cleanup_test_env(dirname, loop_device_name):
        cmd = "if losetup -l {0};then losetup -d {0};fi;".format(loop_device_name)
        cmd += "umount -l {0};rm -rf {0};".format(dirname)
        process.system_output(cmd, shell=True)

    def prepare_tmpfs_folder(dirname):
        cmd = "umount -l {0};rm -rf {0};mkdir -p {0};".format(dirname)
        process.system_output(cmd, ignore_status=True, shell=True)
        cmd = "mount -t tmpfs -o rw,nosuid,nodev,seclabel tmpfs {}".format(dirname)
        process.system_output(cmd, shell=True)

    def create_image_on_loop_device(backend_img, device_img):
        backend_img.create(backend_img.params)
        backend_filename = backend_img.image_filename
        loop_device_name = device_img.image_filename
        cmd = "losetup -d {}".format(loop_device_name)
        process.system_output(cmd, ignore_status=True, shell=True)
        cmd = "losetup {0} {1} && chmod 666 {0}".format(
            loop_device_name, backend_filename
        )
        process.system_output(cmd, shell=True)
        device_img.create(device_img.params)

    def update_loop_device_backend_size(backend_img, device_img, size):
        cmd = "qemu-img resize -f raw %s %s && losetup -c %s" % (
            backend_img.image_filename,
            size,
            device_img.image_filename,
        )
        process.system_output(cmd, shell=True)

    current_size = int(params["begin_size"][0:-1])
    max_size = int(params["max_size"][0:-1])
    increment_size = int(params["increment_size"][0:-1])
    size_unit = params["increment_size"][-1]
    guest_cmd = params["guest_cmd"]

    loop_device = process.run("losetup -f").stdout.decode().strip()
    params["image_name_stg1"] = loop_device
    params["loop_device"] = loop_device

    loop_device_backend_img_tag = params["loop_device_backend_img_tag"]
    loop_device_img_tag = params["loop_device_img_tag"]

    loop_device_backend_img_param = params.object_params(loop_device_backend_img_tag)
    loop_device_img_param = params.object_params(loop_device_img_tag)
    tmpfs_folder = params.get("tmpfs_folder", "/tmp/xtmpfs")

    if loop_device_backend_img_param["image_format"] != "raw":
        test.cancel("Wrong loop device backend image format in config file.")

    error_context.context("Start to setup tmpfs folder", test.log.info)
    prepare_tmpfs_folder(tmpfs_folder)

    error_context.context("Start to create image on loop device", test.log.info)
    loop_device_backend_img = QemuImg(
        loop_device_backend_img_param,
        data_dir.get_data_dir(),
        loop_device_backend_img_tag,
    )
    loop_device_img = QemuImg(
        loop_device_img_param, data_dir.get_data_dir(), loop_device_img_tag
    )
    create_image_on_loop_device(loop_device_backend_img, loop_device_img)

    try:
        # start to boot vm
        params["start_vm"] = "yes"
        timeout = int(params.get("login_timeout", 360))
        os_type = params["os_type"]
        driver_name = params.get("driver_name")
        disk_serial = params["disk_serial"]

        env_process.preprocess_vm(test, params, env, params["main_vm"])
        error_context.context("Get the main VM", test.log.info)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        session = vm.wait_for_login(timeout=timeout)
        if os_type == "windows" and driver_name:
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name, timeout
            )

        if os_type == "windows":
            img_size = loop_device_img_param["image_size"]
            guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = utils_disk.get_windows_disks_index(session, img_size)[0]
            utils_disk.update_windows_disk_attributes(session, disk)
            test.log.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"

        else:
            output_path = get_linux_drive_path(session, disk_serial)

        if not output_path:
            test.fail("Can not get output file path in guest.")

        test.log.debug("Get output file path %s", output_path)

        guest_cmd = guest_cmd % output_path
        wait_timeout = int(params.get("wait_timeout", 60))

        session.sendline(guest_cmd)

        test.assertTrue(vm.wait_for_status("paused", wait_timeout))

        while current_size < max_size:
            current_size += increment_size
            current_size_string = str(current_size) + size_unit

            error_context.context(
                "Update backend image size to %s" % current_size_string, test.log.info
            )
            update_loop_device_backend_size(
                loop_device_backend_img, loop_device_img, current_size_string
            )

            vm.monitor.cmd("cont")

            # Verify the guest status
            if current_size < max_size:
                test.assertTrue(vm.wait_for_status("paused", wait_timeout))
            else:
                test.assertTrue(vm.wait_for_status("running", wait_timeout))
    finally:
        cleanup_test_env(tmpfs_folder, params["loop_device"])
