import random
import re

from virttest import data_dir, env_process, error_context, qemu_storage, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Verify max luns support for one channel of spapr-vscsi.

    Step:
     1. Boot a guest with 32 luns for one channel
     2. Boot a guest with 33 luns for one channel

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    timeout = float(params.get("login_timeout", 240))
    stg_image_num = int(params.get("stg_image_num"))
    stg_image_name = params.get("stg_image_name", "images/%s")
    channel = params.get("channel")
    error_info = params["error_info"]

    for i in range(stg_image_num):
        name = "stg%d" % i
        params["images"] += " %s" % name
        params["image_name_%s" % name] = stg_image_name % name
        params["blk_extra_params_%s" % name] = channel
        params["drive_port_%s" % name] = i
        params["scsi_hba_%s" % name] = "spapr-vscsi"
    if params["luns"] == "lun_33":
        img_params = params.object_params("stg32")
        image = qemu_storage.QemuImg(img_params, data_dir.get_data_dir(), "stg32")
        params["extra_params"] = (
            "-blockdev node-name=file_stg32,\
driver=file,auto-read-only=on,discard=unmap,aio=threads,filename=%s,\
cache.direct=on,cache.no-flush=off -blockdev node-name=drive_stg32,\
driver=qcow2,read-only=off,cache.direct=on,cache.no-flush=off,\
file=file_stg32 -device scsi-hd,lun=32,id=stg32,bus=spapr_vscsi0.0,\
drive=drive_stg32,write-cache=on,channel=0"
            % image.image_filename
        )
        image.create(params)
    params["start_vm"] = "yes"
    try:
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
    except virt_vm.VMCreateError as e:
        if error_info not in e.output:
            test.fail("%s is not reported by QEMU" % error_info)

    if params["luns"] == "lun_32":
        session = vm.wait_for_login(timeout=timeout)
        o = session.cmd_output("lsblk -o SUBSYSTEMS|grep vio|wc -l")
        if int(o) != stg_image_num:
            test.fail("Wrong disks number")
        o = session.cmd_output("lsblk -o KNAME,SUBSYSTEMS|grep vio")
        disks = re.findall(r"(sd\w+)", o, re.M)
        disk = random.choice(disks)
        cmd_w = "dd if=/dev/zero of=/dev/%s bs=1M count=8" % disk
        cmd_r = "dd if=/dev/%s of=/dev/null bs=1M count=8" % disk
        error_context.context("Do dd writing test on the data disk.", test.log.info)
        status = session.cmd_status(cmd_w, timeout=timeout)
        if status != 0:
            test.error("dd writing test failed")
        error_context.context("Do dd reading test on the data disk.", test.log.info)
        status = session.cmd_status(cmd_r, timeout=timeout)
        if status != 0:
            test.error("dd reading test failed")

        session.close()
        vm.destroy(gracefully=True)
