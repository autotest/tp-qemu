import re
import logging

from autotest.client.shared import error

from virttest import utils_test
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    Update virtio driver:
    1) Boot up guest with default devices and virtio_win iso
    2) Install virtio driver
    3) Check dirver info

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def reboot(vm, session=None):
        nic_idx = len(vm.virtnet) - 1
        while nic_idx >= 0:
            try:
                return vm.reboot(session, nic_index=nic_idx)
            except Exception:
                nic_idx -= 1
                if nic_idx < 0:
                    raise
                logging.warn("Unable to login guest, "
                             "try to login via nic %d" % nic_idx)

    def get_installation_log(vm, session=None):
        """
        Copy driver debug files DPINST.log and setupapi.dev.log
        from guest to host
        """
        error.context("Copy installation log from guest to host", logging.info)
        debug_files = "C:\Windows\DPINST.log,C:\Windows\inf\setupapi.dev.log"
        driver_logs = params.get("driver_debug_file", debug_files).split(",")

        for log_file in driver_logs:
            logging.info("Copy debug file %s from guest to host" % log_file)
            try:
                vm.copy_files_from(log_file, test.resultsdir)
            except Exception, detail:
                logging.error("Failed to retrieve debug file %s from guest" %
                              (log_file, detail))

    def get_driver_from_cdrom(driver_name, session):
        """
        Get driver path from virtio-win.iso, and driver version from inf file

        :param driver_name: name of the driver
        return: driver path and driver version
        """
        error.context("Get driver driver path and driver version"
                      " from virtio-win iso", logging.info)
        device_key = params.get("device_key", "VolumeName like '%virtio-win%'")
        alias_map = params.get("guest_alias")
        guest_name = params["guest_name"]

        if alias_map:
            guest_list = dict([x.split(":") for x in alias_map.split(",")])
            guest_name = guest_list[guest_name]

        virtio_win_disk = utils_misc.get_win_disk_vol(session, device_key)
        if not virtio_win_disk:
            raise error.Error("Didn't find virtio-win iso in guest")

        driver_path = "%s:\%s\%s" % (virtio_win_disk, driver_name, guest_name)
        cmd = "dir /B %s\*.inf" % driver_path
        status, output = session.cmd_status_output(cmd)
        if status:
            raise error.TestError("%s" % output)
        if not output:
            raise error.TestError("Didn't find files in %s, pls check if the"
                                  " driver folder is existing" % driver_path)
        inf_file = "%s\%s" % (driver_path, output.split()[0])

        logging.info("Get driver version from %s" % inf_file)
        output = session.cmd("type %s" % inf_file)
        ver_pattern = "DriverVer=(.*)"
        version = re.findall(ver_pattern, output)[0]
        driver_ver = int(version.split(".")[-1])

        return (driver_path, driver_ver)

    def driver_install(driver_path, session):
        """
        Install driver and copy driver debug log to host

        :param driver_path: path of the driver
        """
        driver_install_cmd = params.get("driver_install_cmd")
        winutils = utils_misc.get_winutils_vol(session)
        install_cmd = driver_install_cmd % (winutils, driver_path)
        status, output = session.cmd_status_output(install_cmd, timeout=120)
        get_installation_log(vm)

    def check_driver_version(session):
        device_name = params["device_name"]
        driver_ver_cmd = params.get("driver_version_cmd") % device_name
        s, output = session.cmd_status_output(driver_ver_cmd)
        if s:
            raise error.TestFail(output)
        driver_version = output.split()[-1].split(".")[-1]
        return int(driver_version)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    driver_name = params["driver_name"]
    driver_info = get_driver_from_cdrom(driver_name, session)
    driver_path = driver_info[0]
    driver_to_install = driver_info[1]

    error.context("Update %s to version %s" %
                  (driver_name, driver_to_install), logging.info)
    driver_install(driver_path, session)

    if params.get("reboot") == "yes":
        error.context("Reboot guest after driver installation", logging.info)
        session = reboot(vm, session)
    error.context("Get driver version after update", logging.info)
    current_version = check_driver_version(session)

    if driver_to_install != current_version:
        raise error.TestFail("Driver installation failed,"
                             "Current driver version: %s "
                             "Expected driver version: %s "
                             "pls check driver debug file for the details"
                             % (current_version, driver_to_install))
    logging.info("Current driver version: %s" % current_version)

    if params.get("test_after_update"):
        test_after_update = params.get("test_after_update")
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type=test_after_update)
