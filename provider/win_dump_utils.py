"""
Windows dump related utilities.
"""

import logging
import os

from avocado.utils import process
from virttest import env_process, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


def set_vm_for_dump(test, params):
    """
    Update vm mem and image size params to match dump generate and analysed.

    :param test: kvm test object
    :param params: Params object
    """
    host_free_mem = utils_misc.get_mem_info(attr="MemFree")
    host_avail_disk = int(process.getoutput(params["get_avail_disk"]))
    sys_image_size = int(
        float(utils_misc.normalize_data_size(params["image_size"], "G"))
    )
    if host_avail_disk < (host_free_mem // 1024**2) * 1.2 + sys_image_size:
        avail_dump_size = host_avail_disk - sys_image_size
        params["mem"] = str(int((avail_dump_size) * 0.8 // 2.4) * 1024)
    image_size_stg = int(
        float(utils_misc.normalize_data_size("%sM" % params["mem"], "G")) * 1.4
    )
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

    output = vm.monitor.human_monitor_cmd("dump-guest-memory -w %s" % dump_file)
    if output and "warning" not in output:
        test.fail("Save dump file failed as: %s" % output)
    else:
        cmd = "ls -l %s | awk '{print $5}'" % dump_file
        dump_size = int(process.getoutput(cmd))
        if dump_size == 0:
            test.fail("The size of dump file is %d" % dump_size)

    # Verify dump file can be opened
    try:
        with open(dump_file, "rb") as f:
            f.read(1)
    except IOError as e:
        test.fail("Dump file %s cannot be opened: %s" % (dump_file, e))

    dump_name_zip = "%s.zip" % dump_name
    process.system(
        "cd %s && zip %s %s" % (tmp_dir, dump_name_zip, dump_name), shell=True
    )
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
    LOG_JOB.info("Install Windows Debug Tools in guest.")
    windbg_unzip_cmd = params["windbg_unzip_cmd"]
    windbg_unzip_cmd = utils_misc.set_winutils_letter(session, windbg_unzip_cmd)
    status, output = session.cmd_status_output(windbg_unzip_cmd, timeout=120)
    if status:
        test.error("unzip dump file failed as:\n%s" % output)

    windbg_install_cmd = params["windbg_install_cmd"]
    session.cmd(windbg_install_cmd)

    if not utils_misc.wait_for(
        lambda: check_windbg_installed(params, session),
        timeout=60,
        first=10,
        # first=10 lets the silent WinDbg install settle before polling.
        step=5,
    ):
        test.fail("windbg tool has not been installed")
    else:
        LOG_JOB.info("windbg tool installation completed")


def check_windbg_installed(params, session):
    """
    Check Windows Debug Tools is installed

    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    chk_windbg_cmd = params["chk_windbg_cmd"]
    status, _ = session.cmd_status_output(chk_windbg_cmd)
    return False if status else True


def disable_security_alert(params, session):
    """
    Disable the security alert for windows internet access.

    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    query_cmd = 'reg query HKU | findstr /I /e "500"'
    output = session.cmd_output(query_cmd)
    cmd = 'reg add "%s\\Software\\Microsoft\\Windows\\CurrentVersion'
    cmd += '\\Internet Settings" /v WarnonZoneCrossing /d 0 /t '
    cmd += "REG_DWORD /f"
    session.cmd(cmd % output)


def dump_windbg_check(test, params, session):
    """
    Check the dump file can be open through windbg tool.

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param session: The guest session object.
    """
    LOG_JOB.info("Check the dump file can be opened by windbg tool")
    chk_dump_cmd = params["chk_dump_cmd"]
    log_file = params["dump_analyze_file"]
    chk_dump_cmd = utils_misc.set_winutils_letter(session, chk_dump_cmd)
    status, output = session.cmd_status_output(chk_dump_cmd)
    if status:
        test.fail("Failed to check dump file by windbg,command out is %s" % output)
    if not utils_misc.wait_for(
        lambda: check_log_exist(session, log_file), timeout=480, step=10
    ):
        test.error("Cannot generate dump analyze log.")
    chk_id_cmd = params["chk_id_cmd"] % log_file
    if utils_misc.wait_for(
        lambda: not session.cmd_status(chk_id_cmd), timeout=60, step=5
    ):
        LOG_JOB.info("Check dump file passed")
    else:
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


def dump_cdb_check(test, params, session, dump_path):
    """
    Analyze a Windows dump file using cdb.exe (command-line debugger).

    This replaces the previous AutoIt + WinDbg GUI approach with a simpler
    and more reliable command-line method.
    The cdb.exe path is configured per platform in the cfg file (cdb_path).

    :param test: kvm test object
    :param params: the dict used for parameters.
    :param session: The guest session object.
    :param dump_path: Full path to the dump file in guest, e.g. "G:\\Memory.dmp".
    """
    LOG_JOB.info("Analyzing dump file using cdb.exe command-line debugger")
    cdb_path = params["cdb_path"]
    cdb_timeout = params.get_numeric("cdb_timeout", 600)
    cdb_keyword = params.get("cdb_keyword", "LIVE_SYSTEM_DUMP (161)")
    LOG_JOB.info("Dump file path: %s", dump_path)

    # Pre-flight: verify tools and dumps exist
    status, output = session.cmd_status_output('dir "%s"' % cdb_path)
    if status:
        test.error("cdb.exe not found at: %s" % cdb_path)

    status, output = session.cmd_status_output('dir "%s"' % dump_path)
    if status:
        test.error("Dump file not found at: %s" % dump_path)

    cdb_cmd = '"%s" -z "%s" -c "!analyze -v; q"' % (cdb_path, dump_path)
    LOG_JOB.info("Running cdb command: %s", cdb_cmd)
    status, output = session.cmd_status_output(cdb_cmd, timeout=cdb_timeout)
    LOG_JOB.info("cdb.exe output:\n%s", output)
    if status:
        LOG_JOB.warning("cdb.exe returned non-zero exit code: %s", status)

    if cdb_keyword in output:
        LOG_JOB.info("Dump analysis with cdb.exe passed")
    else:
        test.fail(
            "Dump analysis check failed, keyword %s not found in output:\n%s"
            % (cdb_keyword, output)
        )
