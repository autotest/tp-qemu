import argparse
import logging
import os
import re
import shutil
import subprocess
import sys

logger = logging.getLogger(f"avocado.test.{__name__}")


def cmd_output(cmd):
    """
    Execute specified cmd and get the cmd output.

    :param cmd: Cmd which will be executed.
    """
    logger.debug("Sending command: %s", cmd)
    try:
        p = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception as err:
        error_msg = f"Failed to execute cmd {cmd}!\n" f"Details refers: {err}"
        logger.error(error_msg)
        sys.exit(1)
    stdoutput = p.stdout.readlines()
    logger.debug("Command output is %s", stdoutput)


def getdpinst(vol_utils):
    """
    Get dpinst.exe and dpinst.xml.

    :param vol_utils: Volume of Win_utils.
    """
    if os.environ.get("PROCESSOR_ARCHITECTURE") == "AMD64":
        dpinst_dir = r"%s\dpinst_64.exe" % vol_utils
    else:
        dpinst_dir = r"%s\dpinst_32.exe" % vol_utils
    if not os.path.exists(r"C:\dpinst.exe"):
        shutil.copy(dpinst_dir, r"C:\dpinst.exe")
    else:
        logger.debug("dpinst.exe is already existed")
    if not os.path.exists(r"C:\dpinst.xml"):
        dpinst_xml = r"%s\dpinst.xml" % vol_utils
        shutil.copy(dpinst_xml, r"C:\dpinst.xml")
    else:
        logger.debug("dpinst.xml is already existed")


def certutil(vol_utils):
    """
    Install certificate.

    :param vol_utils: Volume of Win_utils.
    """
    certutil_cmd = r"certutil -addstore -f TrustedPublisher %s\redhat.cer" % vol_utils
    if not os.path.exists(r"C:\certutil.exe"):
        shutil.copy(r"%s\certutil.exe" % vol_utils, r"C:\certutil.exe")
    if not os.path.exists(r"C:\certadm.dll"):
        shutil.copy(r"%s\certadm.dll" % vol_utils, r"C:\certadm.dll")
    logger.info("Install certificate!")
    cmd_output(certutil_cmd)


def install_driver(driver_path, driver_name, vol_utils):
    """
    Install the specified driver.

    :param driver_path: Driver path which will be installed.
    :param driver_name: Driver name which will be installed.
    :param vol_utils: Volume of Win_utils.
    """
    install_driver_cmd = r"C:\dpinst.exe /A /PATH %s /C /LM /Q /F" % driver_path
    certutil(vol_utils)
    logger.info("Install driver %s!", driver_name)
    cmd_output(install_driver_cmd)


def get_inf_files(driver_path, driver_name):
    """
    Get inf file path.exists

    :param driver_path: Driver path which will be installed.
    :param driver_name: Driver name which will be installed.
    :return inf_files: Inf file path.
    """
    inf_name = ("%s.inf" % driver_name).lower()
    inf_files = []
    for root, dirs, files in os.walk(driver_path):
        files_path = map(lambda x: os.path.join(root, x), files)
        inf_files += list(filter(lambda x: x.lower().endswith(inf_name), files_path))
    return inf_files


def uninstall_driver(driver_name):
    """
    Uninstall all specified drivers.
    e.g. has installed 105 and 110 versions for netkvm driver,
         both 105 and 110 will be uninstalled.

    :param driver_name: Driver name which will be installed.
    """
    driver_store = r"C:\Windows\system32\DriverStore\FileRepository"
    uninstall_driver_cmd = r"C:\dpinst.exe /U %s /C /LM /Q /D"
    if not os.path.exists(driver_store):
        logger.error("Driver store path %s does not exist.", driver_store)
        sys.exit(1)
    logger.info("Uninstall driver !")
    inf_files = get_inf_files(driver_store, driver_name)
    for ini_file in inf_files:
        cmd_output(uninstall_driver_cmd % ini_file)


def get_current_driver_ver(device_name):
    """
    Get current driver version for the specified driver.

    :param device_name: Corresponding device name with driver.
    :return: Current driver version.
    """
    key = r"\d*\.\d*\.\d*\.\d*"
    get_driver_ver_cmd = (
        "wmic path win32_pnpsigneddriver where"
        " Devicename='%s' get driverversion" % device_name
    )
    driver_version = os.popen(get_driver_ver_cmd).read()
    if not driver_version.strip():
        return ""
    return re.findall(key, driver_version, re.M)[-1].strip()


def get_expected_driver_ver(driver_path, driver_name):
    """
    Get expected driver version, which is wanted to be installed.

    :param driver_path: Driver path which will be installed.
    :param driver_name: Driver name which will be installed.
    :return: Expected driver version.
    """
    inf_file = get_inf_files(driver_path, driver_name)
    with open("".join(inf_file)) as fd:
        driver_info = os.linesep.join(fd.readlines())
        return re.findall(r"DriverVer=.*,([\d.]+)", driver_info, re.M)[-1].strip()


def verify_driver_ver(driver_path, device_name, driver_name):
    """
    Verify the installed driver version is same as the expected.

    :param driver_path: Driver path which will be installed.
    :param device_name: Corresponding device name with driver.
    :param driver_name: Driver name which will be installed.
    """
    current_driver_ver = get_current_driver_ver(device_name)
    expected_driver_ver = get_expected_driver_ver(driver_path, driver_name)
    logger.info("Compare whether driver version is same as expected.")
    if current_driver_ver != expected_driver_ver:
        error_msg = (
            "Driver installation failed !\n"
            "Current driver version %s is not equal"
            " to the expected %s." % (current_driver_ver, expected_driver_ver)
        )
        logger.error(error_msg)
        sys.exit(1)
    logger.info("Current driver version %s is same as expected.", current_driver_ver)


def show_log_output(result_file):
    """
    Show execution logs.

    :param result_file: File which saves execution logs.
    """
    with open(result_file) as fd:
        print(os.linesep.join(fd.readlines()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Windows Driver Operation")
    parser.add_argument(
        "-i",
        "--install_driver",
        help="operation for install driver",
        dest="install_driver",
        action="store_true",
    )
    parser.add_argument(
        "-u",
        "--uninstall_driver",
        help="operation for uninstall driver",
        dest="uninstall_driver",
        action="store_true",
    )
    parser.add_argument(
        "-q",
        "--query_driver",
        help="operation for query driver",
        dest="query_driver",
        action="store_true",
    )
    parser.add_argument(
        "-v",
        "--verify_driver",
        help="operation for verify driver",
        dest="verify_driver",
        action="store_true",
    )
    parser.add_argument(
        "-o",
        "--log_output",
        help="operation for show log output",
        dest="log_output",
        action="store_true",
    )
    parser.add_argument(
        "--driver_path", help="driver path", dest="driver_path", action="store"
    )
    parser.add_argument(
        "--driver_name", help="driver name", dest="driver_name", action="store"
    )
    parser.add_argument(
        "--device_name",
        help="the corresponding device name with driver",
        dest="device_name",
        action="store",
    )
    parser.add_argument(
        "--vol_utils", help="volume of WIN_UTILS", dest="vol_utils", action="store"
    )
    arguments = parser.parse_args()

    result_file = r"C:\driver_install.log"
    logger = logging.getLogger("driver_install")
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(result_file, mode="a+")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    if not os.path.exists(arguments.driver_path):
        logger.error("Driver path %s does not exist", arguments.driver_path)
        sys.exit(1)

    if arguments.uninstall_driver:
        getdpinst(arguments.vol_utils)
        uninstall_driver(arguments.driver_name)
    elif arguments.install_driver:
        getdpinst(arguments.vol_utils)
        install_driver(
            arguments.driver_path, arguments.driver_name, arguments.vol_utils
        )
    elif arguments.query_driver:
        current_driver_ver = get_current_driver_ver(arguments.device_name)
        msg = "Current driver version for %s is %s" % (
            arguments.driver_name,
            current_driver_ver,
        )
        logger.debug(msg)
    elif arguments.verify_driver:
        verify_driver_ver(
            arguments.driver_path, arguments.device_name, arguments.driver_name
        )
    elif arguments.log_output:
        print("Execution log:\n")
        show_log_output(result_file)
        print("DPINST.log:\n")
        show_log_output(r"C:\Windows\DPINST.log")
