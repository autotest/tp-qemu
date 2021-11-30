"""
Windows dump related utilities.
"""
import os
import logging

from avocado.utils import process
from virttest import env_process
from virttest import utils_misc


def set_vm_for_dump(test, params):
    """
    Update vm mem and image size params to match dump generate and analysed.

    :param test: kvm test object
    :param params: Params object
    """
    host_free_mem = utils_misc.get_mem_info(attr='MemFree')
    host_avail_disk = int(process.getoutput(params["get_avail_disk"]))
    sys_image_size = int(float(
            utils_misc.normalize_data_size(params["image_size"], "G")))
    if host_avail_disk < (host_free_mem // 1024**2) * 1.2 + sys_image_size:
        params["mem"] = (host_avail_disk - sys_image_size) * 0.8 // 2.4 * 1024
    image_size_stg = int(float(
            utils_misc.normalize_data_size(params["mem"] + "M", "G")) * 1.4)
    params["image_size_stg"] = str(image_size_stg) + "G"

    params["force_create_image_stg"] = "yes"
    image_params = params.object_params("stg")
    env_process.preprocess_image(test, image_params, "stg")


def generate_mem_dump(test, params, vm):
    """
    Generate the Memory.dmp file through qemu side.

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param vm: VM object.
    """
    tmp_dir = params["tmp_dir"]
    if not os.path.isdir(tmp_dir):
        process.system("mkdir %s" % tmp_dir)
    dump_name = utils_misc.generate_random_string(4) + "Memory.dmp"
    dump_file = tmp_dir + "/" + dump_name

    output = vm.monitor.human_monitor_cmd('dump-guest-memory -w %s'
                                          % dump_file)
    if output:
        test.fail("Save dump file failed as: %s" % output)
    else:
        cmd = "ls -l %s | awk '{print $5}'" % dump_file
        dump_size = int(process.getoutput(cmd))
        if dump_size == 0:
            test.fail("The size of dump file is %d" % dump_size)

    dump_name_zip = "%s.zip" % dump_name
    process.system("cd %s && zip %s %s" % (tmp_dir, dump_name_zip,
                                           dump_name), shell=True)
    dump_file_zip = tmp_dir + "/" + dump_name_zip
    return dump_file, dump_file_zip


def install_windbg(test, params, session, timeout=600):
    """
    Install Windows Debug Tools.

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param session: The guest session object.
    :param timeout: waiting debug tool install finish.
    """
    logging.info("Install Windows Debug Tools in guest.")
    windbg_install_cmd = params["windbg_install_cmd"]
    windbg_install_cmd = utils_misc.set_winutils_letter(session,
                                                        windbg_install_cmd
                                                        % params["feature"])
    session.cmd(windbg_install_cmd)
    if not utils_misc.wait_for(lambda: check_windbg_installed(params, session),
                               timeout=timeout):
        test.fail("windbg tool has not been installed")


def update_dbg_dll(params, session):
    """
    Update Windows Debug Tools dbg dll file.
    Here's a fix workarond for windbg running, it's not so stable sometimes,
    better repalce 2 files dbgeng.dll and dbghelp.dll before using.

    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    windbg_path = params["windbg_path"]
    dbgeng_cmd = params["dbgeng_cmd"] % windbg_path
    dbghelp_cmd = params["dbghelp_cmd"] % windbg_path
    session.cmd(dbgeng_cmd)
    session.cmd(dbghelp_cmd)


def check_windbg_installed(params, session):
    """
    Check Windows Debug Tools is installed

    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    check_cmd = params["chk_windbg_cmd"] % params["windbg_path"]
    status, _ = session.cmd_status_output(check_cmd)
    return False if status else True


def dump_windbg_check(test, params, session):
    """
    Check the dump file can be open through windbg tool.

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    logging.info("Check the dump file can be opened by windbg tool")
    chk_dump_cmd = params["chk_dump_cmd"]
    log_file = params["dump_analyze_file"]
    chk_dump_cmd = utils_misc.set_winutils_letter(session,
                                                  chk_dump_cmd)
    session.cmd(chk_dump_cmd)
    if not utils_misc.wait_for(lambda: check_log_exist(session, log_file),
                               timeout=120):
        test.error("Cannot generate dump analyze log.")
    chk_id_cmd = params["chk_id_cmd"] % log_file
    status, output = session.cmd_status_output(chk_id_cmd)
    if status:
        output = session.cmd_output("type %s" % log_file)
        test.fail("Check dump file failed, output as %s" % output)


def check_log_exist(session, log_file):
    """
    Check if the analyzed log of dump file is exist.

    :param session: The guest session object.
    :param log_file: The log file of dump analyze.
    """
    chk_log_exist = "dir %s" % log_file
    status, _ = session.cmd_status_output(chk_log_exist)
    return False if status else True
