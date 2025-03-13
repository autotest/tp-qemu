"""Check memory leak on block devices"""

import os
import re
import time

from avocado.utils import process
from virttest import arch, env_process, error_context
from virttest import data_dir as virttest_data_dir
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Check memory leak on block devices test

    1) Using valgrind to boot the main vm with multi disks.
    2) Execute IO on multi disks
    3) Wait the IO doing in minutes.
    4) Destroy the VM.
    5) Check leak or overflow info in valgrind log .


    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _execute_io_in_guest(serial=None):
        devs = ""
        if serial:
            drive = get_linux_drive_path(session, serial)
            if drive:
                devs += drive.replace("/dev/", "") + " "
        else:
            for serial in data_images:
                drive = get_linux_drive_path(session, serial)
                if drive:
                    devs += drive.replace("/dev/", "") + " "

        guest_io_cmd = params["guest_io_cmd"] % devs
        host_script = params["host_script"]
        guest_dir = params["guest_dir"]
        deps_dir = virttest_data_dir.get_deps_dir()
        host_file = os.path.join(deps_dir, host_script)
        vm.copy_files_to(host_file, guest_dir)
        logger.info("Execute io:%s", guest_io_cmd)
        session.sendline("$SHELL " + guest_io_cmd)

    def _get_scsi_debug_disk():
        output = (
            process.system_output(
                "lsscsi -giss|grep scsi_debug", shell=True, ignore_status=True
            )
            .decode()
            .strip()
        )
        test.log.info("Host cmd output '%s'", output)
        disk_info = []
        if len(output) < 10:
            test.log.warning("Can not find scsi_debug disk")
            return

        output = output.split("\n")
        for disk in output:
            info = disk.split()
            disk_dic = {
                "path": info[5],
                "wwn": info[6],
                "sg": info[7],
                "size": info[8],
                "all": disk,
            }
            disk_info.append(disk_dic)

        test.log.info(disk_info)
        return disk_info

    if arch.ARCH in ("ppc64", "ppc64le"):
        out = process.system_output("lscfg --list firmware -v", shell=True).decode()
        ver = float(re.findall(r"\d\.\d", out)[0])
        if ver >= 6.3:
            # bz2235228,cancel test due to known product bug.
            test.cancel(
                "Skip test for xive kvm interrupt guest due to"
                " known host crash issue."
            )

    logger = test.log

    vm = None
    disk_wwn = None
    if params.get("get_scsi_device") == "yes":
        scsi_debug_devs = _get_scsi_debug_disk()
        if scsi_debug_devs:
            dev = scsi_debug_devs[0]
            disk_wwn = dev["wwn"]
            if params["drive_format_stg1"] == "scsi-generic":
                params["image_name_stg1"] = dev["sg"]
            else:
                params["image_name_stg1"] = dev["path"]
        else:
            test.fail("Can not find scsi_debug devices")
    try:
        if params.get("not_preprocess", "no") == "yes":
            logger.debug("Ready boot VM : %s", params["images"])
            env_process.process(
                test,
                params,
                env,
                env_process.preprocess_image,
                env_process.preprocess_vm,
            )

        data_images = params["data_images"].split()
        error_context.context("Get the main VM", logger.info)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        timeout = params.get_numeric("login_timeout", 360)
        session = vm.wait_for_login(timeout=timeout)
        time.sleep(params.get_numeric("vm_boot_timeout", 60))
        logger.info("Start to IO in guest")
        _execute_io_in_guest(disk_wwn)
        logger.info("Wait ...")
        time.sleep(params.get_numeric("io_timeout", 300))

        logger.info("Try to cancel IO.")
        session = vm.wait_for_login(timeout=timeout)
        session.cmd(params["guest_cancel_io_cmd"], timeout=timeout)
        logger.info("Ready to destroy vm")
        vm.destroy()
        logger.info("Ready to check vm...")
        cp_cmd = "cp %s %s" % (params["valgrind_log"], test.logdir)
        process.system_output(cp_cmd, shell=True)
        if params.get("leak_check", "yes") == "yes":
            check_cmd = params["leak_check_cmd"]
            out = process.system_output(check_cmd, shell=True).decode()
            leak_threshold = params.get_numeric("leak_threshold")
            logger.info("Find leak:%s,threshold: %d", out, leak_threshold)
            if len(out) and int(out) > leak_threshold:
                test.fail("Find memory leak %s,Please check valgrind.log" % out)

        if params.get("overflow_check", "yes") == "yes":
            check_cmd = params["overflow_check_cmd"]
            out = process.system_output(
                check_cmd, shell=True, ignore_status=True
            ).decode()
            if out and len(out):
                test.fail("Find overflow %s,Please check valgrind.log" % out)
    finally:
        if vm and vm.is_alive():
            vm.destroy(gracefully=False)
