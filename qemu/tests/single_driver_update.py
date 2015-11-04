import re
import logging
from autotest.client.shared import error
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    This Test is mainly used as subtests
    1) Boot up VM
    2) Find the driver from the repo
    3) record the driver version
    4) Copy it to C:\ (If there are two copy the newest one)
    5) Uninstall the driver/downgrade the driver
    6) Reinstall the driver copied to C:\\tmp
    7) Check the driver version whether same as original

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def get_installation_logs(session):
        tmp_debug = "%systemroot%\\DPINST.log,\
                     %systemroot%\\inf\\setupapi.dev.log"
        driver_logs = params.get("driver_debug_file", tmp_debug).split(',')
        error.context("Get Driver installation log", logging.info)
        for _file in driver_logs:
            s, o = session.cmd_status_output("dir %s" % _file)
            if not s:
                output = session.cmd("type %s" % _file)
                _file_host = _file.split("\\")[-1].strip()
                _debug_log = open("%s/%s" % (test.resultsdir, _file_host), "w")
                _debug_log.write("%s\n" % output)
                _debug_log.close()

    def backup_latest_folder(session, folders):
        driver_repo_path = params.get("driver_repo_path")
        tmp_folder = params.get("tmp_folder", 'C:\tmp')
        status, output = session.cmd_status_output("dir /B %s" % tmp_folder)
        if status:
            session.cmd("mkdir %s" % tmp_folder)
        latest_folder = ""
        latest_version = 0
        if len(folders) == 0:
            get_installation_logs(session)
            raise error.TestError("No folder found, \
                                  Pls check whether the driver is installed")
        else:
            for folder in folders:
                cli = "type %s\\%s\\*.inf" % (driver_repo_path, folder)
                output_full = session.cmd(cli)
                key = "DriverVer.*\S"
                output = re.findall(key, output_full, re.M)[-1]
                if int(output.split('.')[-1]) >= latest_version:
                    latest_folder = folder
                    latest_version = int(output.split('.')[-1])
        logging.info("Latest installed version is %s"
                     % latest_version)
        session.cmd("xcopy %s\%s %s\%s /S /Y /I"
                    % (driver_repo_path,
                       latest_folder,
                       tmp_folder,
                       latest_folder))
        return latest_folder

    def driver_folder_find(session):
        driver_name = params.get("driver_name")
        driver_repo_path = params.get("driver_repo_path")
        search_cmd = "dir /B  %s\%s.inf*" % (driver_repo_path, driver_name)
        status, output = session.cmd_status_output(search_cmd)
        folders = []
        if not status:
            key = "^%s.*\S" % driver_name
            folders = re.findall(key, output, re.M)
            logging.info("All folders %s" % folders)
        return folders

    def driver_uninstall(session, folders):
        driver_uninstall_command = params.get("driver_uninstall_command")
        driver_repo_path = params.get("driver_repo_path")
        driver_name = params.get("driver_name")
        for folder in folders:
            uninstall_command = driver_uninstall_command % (
                driver_repo_path,
                folder,
                driver_name)
            error.context("uninstall cli %s"
                          % uninstall_command, logging.info)
            status, output = session.cmd_status_output(uninstall_command)
            if status == 1073741824:
                logging.info("reboot is required")
                session = vm.reboot(session)
            elif status == 0:
                logging.info("driver uninstalled successfully")
            elif status == -2147483648:
                logging.info("No Driver Store Entry %s"
                             % driver_uninstall_command)
                session = vm.reboot(session)
            else:
                get_installation_logs(session)
                raise error.TestError("unknown error %s"
                                      % status, logging.info)

    def driver_install(session, folder, downgrade=False):
        install_cmd = params.get("driver_install_command")
        tmp_folder = params.get("tmp_folder", 'C:\\tmp\\')
        winutils = utils_misc.get_winutils_vol(session)
        if downgrade:
            tmp_folder = winutils + ":"
        install_cmd = install_cmd % (winutils, tmp_folder, folder)
        error.context("install %s" % install_cmd, logging.info)
        status, output = session.cmd_status_output(install_cmd)
        if status == -2147483648:
            msg = "Testing Failed"
            msg += "it is driver not digital signed by either"
            msg += "Microsoft or Redhat "
            msg += "pls report a bug agaist virtio-win component"
            get_installation_logs(session)
            raise error.TestError("%s, %s" % (msg, output), logging.info)
        elif status == 1:
            logging.info("driver installed successfully %s"
                         % output)
            logging.debug("yonit bitmap benchmark was not found")
        elif status == 0:
            logging.info("driver downgrade successfully %s"
                         % output)
        else:
            msg = "return %s ,pls check C:\windows\dpinst.log for help" % status
            get_installation_logs(session)
            raise error.TestError("%s, %s" % (msg, output), logging.info)

    def get_current_version(session):
        device_name = params.get("device_name")
        driver_version_command = params.get("driver_version_command")
        device_name_quota = "\"%s\"" % device_name
        exec_dri_version = driver_version_command % device_name_quota
        status, outputfull = session.cmd_status_output(exec_dri_version)
        if status == 0:
            key = "\d*\.\d*\.\d*\.\d*"
            output = re.findall(key, outputfull, re.M)[-1]
            error.context("current driver version %s" % output, logging.info)
            return int(output.split('.')[-1])

    timeout = int(params.get("timeout", 1800))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    folders = driver_folder_find(session)
    latest_folder = backup_latest_folder(session, folders)
    downgrade = params.get("downgrade")
    version_before = get_current_version(session)
    if downgrade:
        fix_str = params.get("fix_str", "driver_install_cmd_")
        driver_name = params.get("driver_name", "unknown")
        if driver_name == "unknown":
            raise error.TestError("did not find driver")
        old_driver_path = params.get(fix_str + driver_name)
        error.context("install old driver from %s" % old_driver_path, logging.info)
        driver_install(session, old_driver_path, downgrade)
        if version_before < get_current_version(session):
            raise error.TestError("Failed to dowgrade")
    else:
        driver_uninstall(session, folders)
    session = vm.reboot()
    driver_install(session, latest_folder)
    if version_before != get_current_version(session):
        raise error.TestError("Reinstall failed")
    get_installation_logs(session)
