import logging
import re

from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM windows virtio driver signed status check test:
    1) Start a windows guest with virtio driver iso/floppy
    2) Generate a tested driver file list.
    3) use SignTool.exe to verify whether all drivers digital signed

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    signtool_cmd = params.get("signtool_cmd")
    list_files_cmd = params.get("list_files_cmd")
    drive_volume_list = params.objects("drive_volume")
    fails_log = """Failed signature check log:\n"""
    results_all = """All the signature check log:\n"""
    fail_num = 0
    fail_drivers = []
    virtio_drivers = []
    drivers = {}
    need_test_driver = params.objects("tested_drivers")

    def get_os_arch_path(alias_map):
        """
        Get the os path and arch path which would be tested.

        :param session: VM session.
        :param alias_map: all guest_name and os path + arch path mapping info.

        :return os_arch_path_list: Return the os_arch_path_list.
        """
        guest_name = params["guest_name"]
        guest_list = dict([x.split(":") for x in alias_map.split(",")])
        os_arch_path = guest_list[guest_name]
        global os_arch_path_list
        os_arch_path_list = os_arch_path.split("\\")
        return os_arch_path_list

    def filter_all_tested_cat_files(cat_files):
        """
        In all suffix '.cat' files, select that will be tested '.cat' file.

        :param cat_files:all suffix '.cat' files.
        :return True:correct os path, arch path and the dirver_dir
        belong in need_test_driver list, return True.
        """
        pattern = r'(\w:)\\(.+?)\\(.+?)\\(.+?)[\.|\\]'
        ret = re.match(pattern, cat_files, re.I)
        disk_name = ret.group(1)
        os_name = ret.group(3)

        if disk_name == "A:":
            get_os_arch_path(alias_map=params.get("guest_alias_fl"))
            os_path = os_arch_path_list[1]
            arch_path = os_arch_path_list[0]
            plat_name = ret.group(2)
            driver_dir = ret.group(4)
        else:
            get_os_arch_path(alias_map=params.get("guest_alias"))
            os_path = os_arch_path_list[0]
            arch_path = os_arch_path_list[1]
            driver_dir = ret.group(2)
            plat_name = ret.group(4)

        if (os_name == os_path) and (plat_name == arch_path):
            if driver_dir in need_test_driver:
                return True

    def match_cat_and_verified_file(filterd_cat_file):
        """
        Tuple each selected '.cat' file and with same directory '.sys' file;
        Tuple each selected '.cat' file and with same directory '.inf' file;
        Tuple each selected '.cat' file and with same directory 'Wdf' file.

        Collect all tuples in virtio_drivers list to be used signtool test.

        :param filterd_cat_file:each filterd suffix '.cat' file
        """
        pattern = r'\w:\\(.+?)\\(.+?)\\(.+?)[\.|\\]'
        match_ret = re.match(pattern, filterd_cat_file)
        driver_dir = match_ret.group()

        driver_sys = filter(lambda x: driver_dir in x, drivers['.sys'])
        driver_inf = filter(lambda x: driver_dir in x, drivers['.inf'])
        driver_wdf = filter(lambda x: driver_dir in x, drivers['Wdf'])

        cat_sys = map(lambda x: (filterd_cat_file, x), driver_sys)
        cat_inf = map(lambda x: (filterd_cat_file, x), driver_inf)
        cat_wdf = map(lambda x: (filterd_cat_file, x), driver_wdf)
        cat_parm = cat_sys + cat_inf + cat_wdf
        virtio_drivers.extend(cat_parm)

    try:
        error_context.context("Running SignTool check test in guest...",
                              logging.info)
        key = "VolumeName like 'virtio-win%'"
        disk_letter = utils_misc.get_win_disk_vol(session, condition=key) + ":"
        drive_volume_list.append(disk_letter)

        for drive in drive_volume_list:
            for type in ['.cat', '.sys', '.inf', 'Wdf']:
                driver = session.cmd_output(list_files_cmd % (drive, type)).\
                    splitlines()[1:-1]
                drivers[type] = driver

            cat_list = filter(filter_all_tested_cat_files, drivers['.cat'])
            map(match_cat_and_verified_file, cat_list)

            for driver_file in virtio_drivers:
                test_cmd = signtool_cmd % (driver_file[0], driver_file[1])
                test_cmd = utils_misc.set_winutils_letter(session, test_cmd)
                status, result = session.cmd_status_output(test_cmd)
                if status:
                    msg = "Fail command: %s. Output: %s" % (test_cmd, result)
                    logging.error(msg)
                results_all += result
                re_suc = "Number of files successfully Verified: ([0-9]*)"
                try:
                    suc_num = re.findall(re_suc, result, re.M)[0]
                except IndexError:
                    msg = "Fail to get Number of files successfully Verified"
                    logging.error(msg)
                    suc_num = 0

                if int(suc_num) != 1:
                    fails_log += result
                    fail_num += 1
                    fail_drivers.append(driver_file[1])
            virtio_drivers = []

        if fail_num > 0:
            msg = "Following %s driver(s) signature checked failed." % fail_num
            msg += " Please refer to fails.log for details error log:\n"
            msg += "\n".join(fail_drivers)
            test.fail(msg)

    finally:
        with open("%s/fails.log" % test.resultsdir, "w") as fp1:
            fp1.write(fails_log)
        with open("%s/result.log" % test.resultsdir, "w") as fp2:
            fp2.write(results_all)
