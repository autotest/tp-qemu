import re

from avocado.utils import process
from virttest import env_process, error_context, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Test the scsi device with "share-rw" option.

    Steps:
      1. Boot up a guest with a data disk which image format is raw and
         "share-rw" option is "off" or "on".
      2. Run another vm with the data images:
        2.1 Failed to execute the qemu commands due to fail to get "write" lock
            with "share-rw=off"
        2.2 Could execute the qemu commands with "share-rw=on".
      3. Repeat step 1~2 with the drive format is "scsi-block" and "scsi-generic".

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    msgs = ['"write" lock', "Is another process using the image"]
    modprobe_cmd = params.get("modprobe_cmd")
    disk_check_cmd = params.get("disk_check_cmd")
    indirect_image_blacklist = params.get("indirect_image_blacklist").split()

    # In some environments, The image in indirect_image_blacklist
    # does not exist in host. So we need to check the host env
    # first and update the blacklist.
    if disk_check_cmd:
        image_stg_blacklist = params.get("image_stg_blacklist").split()
        matching_images = process.run(
            disk_check_cmd, ignore_status=True, shell=True
        ).stdout_text
        for disk in image_stg_blacklist:
            if not re.search(disk, matching_images):
                indirect_image_blacklist.remove(disk)
        params["indirect_image_blacklist"] = " ".join(indirect_image_blacklist)

        process.run(modprobe_cmd, ignore_status=True, shell=True)
        params["image_raw_device_stg"] = "yes"
        params["indirect_image_select_stg"] = "-1"
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm1 = env.get_vm(params["main_vm"])
    vm1.verify_alive()
    vm1.wait_for_login(timeout=360)

    try:
        error_context.context("Start another vm with the data image.", test.log.info)
        params["images"] = params["images"].split()[-1]
        env_process.preprocess_vm(test, params, env, "avocado-vt-vm2")
        vm2 = env.get_vm("avocado-vt-vm2")
        vm2.verify_alive()
    except virt_vm.VMCreateError as e:
        if params["share_rw"] == "off":
            if not all(msg in str(e) for msg in msgs):
                test.fail("Image lock information is not as expected.")
        else:
            test.error(str(e))
    else:
        vm2.destroy(False, False)
