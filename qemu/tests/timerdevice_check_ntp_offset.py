import os
import time

from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Check the offset of Meinberg NTP for windows guest.

    1) sync the host time with ntp server
    2) boot a windows  guest with network
    3) install diskspd tool and Meinberg NTP
    4) run diskspd benchmark in Administrator user
    5) play a video fullscreen
    6) periodically verify "offset" output of Meinberg NTP

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    def clean_tmp_file():
        if not session.cmd_status("dir %s" % ntp_dst_path):
            session.cmd("rd /s /q %s" % ntp_dst_path)
        ntp_install_path = params["ntp_install_path"]
        ntp_uninstall_cmd = params["ntp_uninstall_cmd"]
        if not session.cmd_status("dir %s" % ntp_install_path):
            session.cmd(ntp_uninstall_cmd)
        diskspd_check_cmd = params["diskspd_check_cmd"]
        diskspd_end_cmd = params["diskspd_end_cmd"]
        if not session.cmd_status("dir %s" % (dst_path + diskspd_name)):
            if not session.cmd_status(diskspd_check_cmd):
                session.cmd(diskspd_end_cmd)
            session.cmd("del %s" % (dst_path + diskspd_name))

    ntp_cmd = params["ntp_cmd"]
    error_context.context("Sync host system time with ntpserver", test.log.info)
    process.system(ntp_cmd, shell=True)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    error_context.context("Install diskspd tool on guest", test.log.info)
    diskspd_dir = params["diskspd_dir"]
    diskspd_name = params["diskspd_name"]
    dst_path = params["dst_path"]
    diskspd_src_path = os.path.join(data_dir.get_deps_dir(diskspd_dir))
    vm.copy_files_to(diskspd_src_path, dst_path)

    error_context.context("Install Meinberg NTP on guest", test.log.info)
    ntp_dir = params["ntp_dir"]
    ntp_name = params["ntp_name"]
    ntp_unattend_file = params["ntp_unattend_file"]
    ntp_dst_path = params["ntp_dst_path"]
    install_ntp_cmd = params["install_ntp_cmd"]
    vm.copy_files_to(data_dir.get_deps_dir(ntp_dir), dst_path)
    session.cmd("cd %s" % ntp_dst_path)
    session.cmd(install_ntp_cmd % (ntp_name, ntp_unattend_file))

    error_context.context("Run diskspd on guest", test.log.info)
    diskspd_run_cmd = params["diskspd_run_cmd"]
    session.cmd("cd %s" % dst_path)
    session.cmd(diskspd_run_cmd)

    error_context.context("Play a video on guest", test.log.info)
    sub_test = params["sub_test"]
    utils_test.run_virt_sub_test(test, params, env, sub_test)

    error_context.context("Check offset of ntp", test.log.info)
    check_offset_cmd = params["check_offset_cmd"]
    sleep_time = params["sleep_time"]
    try:
        for _ in range(params.get_numeric("nums")):
            time.sleep(int(sleep_time))
            ntp_offset = session.cmd_output(check_offset_cmd)
            ntp_offset = float(
                ntp_offset.strip().split("\n")[-1].split()[-2].strip("-+")
            )
            if ntp_offset > 100:
                test.fail("The ntp offset %s is larger than 100ms" % ntp_offset)
    finally:
        clean_tmp_file()
