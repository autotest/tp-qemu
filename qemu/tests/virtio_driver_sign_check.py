import re

from virttest import error_context, utils_misc
from virttest.utils_windows import virtio_win


def get_driver_file_path(session, params):
    """
    Get tested driver path and drive_letter,
    Path like "E:\\vioscsi\\2k8\\x86\\vioscsi.cat/sys/inf"
    or "A:\\i386\\Win2008\\vioscsi.cat".
    drive_letter like "E:" or "A:".

    :param session: VM session
    :param params: Dictionary with the test parameters
    """
    driver_path = params["tested_driver"]
    media_type = params["virtio_win_media_type"]
    get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
    drive_letter = get_drive_letter(session)
    get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
    guest_name = get_product_dirname(session)
    get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
    guest_arch = get_arch_dirname(session)
    path = (
        "{letter}\\{driver}\\{name}\\{arch}\\"
        if media_type == "iso"
        else "{letter}\\{arch}\\{name}\\{driver}"
    ).format(letter=drive_letter, driver=driver_path, name=guest_name, arch=guest_arch)
    return drive_letter, path


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
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    signtool_cmd = params["signtool_cmd"]
    drv_name = params["tested_driver"].lower()
    list_files_cmd = 'dir /s /b %s | find /i "%s" | find "%s"'
    verify_option = params["verify_option"]

    try:
        error_context.context("Running SignTool check test in guest...", test.log.info)
        file_type = [".cat", ".sys", ".inf", "Wdf"]
        # Add a workaround for pvpanic, as there are pvpanic-pci files
        # include in the latest prewhql version,
        # they are for arm support and we no need to test them currently.
        if "pvpanic" in drv_name:
            file_type = ["%s.cat" % drv_name, ".sys", "%s.inf" % drv_name, "Wdf"]
        tested_list = []
        viowin_letter, path = get_driver_file_path(session, params)
        for ftype in file_type:
            cmd = list_files_cmd % (viowin_letter, path, ftype)
            list_file = session.cmd_output(cmd, timeout)
            driver_file = re.findall(r".*%s$" % ftype, list_file, re.M)
            tested_list.extend(driver_file)
        if (len(tested_list) < 3) or (".cat" not in tested_list[0]):
            test.fail("The tested files were not included in %s disk" % viowin_letter)
        signtool_cmd = utils_misc.set_winutils_letter(session, signtool_cmd)
        check_info = "Number of files successfully Verified: (1)"
        for driver_file in tested_list[1:]:
            test_cmd = signtool_cmd % (verify_option, tested_list[0], driver_file)
            status, output = session.cmd_status_output(test_cmd)
            sign_num = re.findall(check_info, output)[0]
            if (status != 0) or (int(sign_num) != 1):
                test.fail(
                    "%s signtool verify failed, check the output details:\n %s"
                    % (driver_file, output)
                )
    finally:
        session.close()
