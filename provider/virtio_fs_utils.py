import logging
import os
import re
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_misc
from virttest.utils_windows import virtio_win

LOG_JOB = logging.getLogger("avocado.test")


def get_virtiofs_driver_letter(test, fs_target, session):
    """
    Get the virtiofs driver letter( Windows guest only )

    :param test: QEMU test object
    :param fs_target: virtio fs target
    :param session: the session of guest
    :return driver_letter: the driver letter of the virtiofs
    """
    error_context.context(
        "Get driver letter of virtio fs target, " "the driver label is %s." % fs_target,
        LOG_JOB.info,
    )
    driver_letter = utils_misc.get_winutils_vol(session, fs_target)
    if driver_letter is None:
        test.fail("Could not get virtio-fs mounted driver letter.")
    return driver_letter


@error_context.context_aware
def basic_io_test(test, params, session):
    """
    Virtio_fs basic io test. Create file on guest and then compare two md5
    values from guest and host.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session from guest
    """
    error_context.context("Running viofs basic io test", LOG_JOB.info)
    test_file = params.get("virtio_fs_test_file", "virtio_fs_test_file")
    windows = params.get("os_type", "windows") == "windows"
    io_timeout = params.get_numeric("fs_io_timeout", 120)
    fs_source = params.get("fs_source_dir", "virtio_fs_test/")
    fs_target = params.get("fs_target", "myfs")
    base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())
    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    host_data = os.path.join(fs_source, test_file)
    try:
        if windows:
            cmd_dd = params.get(
                "virtio_fs_cmd_dd", "dd if=/dev/random of=%s bs=1M count=100"
            )
            driver_letter = get_virtiofs_driver_letter(test, fs_target, session)
            fs_dest = "%s:" % driver_letter
        else:
            cmd_dd = params.get(
                "virtio_fs_cmd_dd",
                "dd if=/dev/urandom of=%s bs=1M " "count=100 iflag=fullblock",
            )
            fs_dest = params.get("fs_dest", "/mnt/" + fs_target)
        guest_file = os.path.join(fs_dest, test_file)
        error_context.context(
            "The guest file in shared dir is %s" % guest_file, LOG_JOB.info
        )
        error_context.context(
            "Creating file under %s inside guest." % fs_dest, LOG_JOB.info
        )
        # for windows, after virtiofs service start up, should wait several seconds
        #  to make the volume active.
        if windows:
            pattern = r"The system cannot find the file specified"
            end_time = time.time() + io_timeout
            while time.time() < end_time:
                status, output = session.cmd_status_output(cmd_dd % guest_file)
                if re.findall(pattern, output, re.M | re.I):
                    time.sleep(2)
                    continue
                if status != 0:
                    test.fail("dd command failed on virtiofs.")
                break
            else:
                test.error(f"Volume is not ready for io within {io_timeout}.")
        else:
            session.cmd(cmd_dd % guest_file, io_timeout)

        if windows:
            guest_file_win = guest_file.replace("/", "\\")
            cmd_md5 = params.get("cmd_md5", "%s: && md5sum.exe %s")
            cmd_md5_vm = cmd_md5 % (driver_letter, guest_file_win)
        else:
            cmd_md5 = params.get("cmd_md5", "md5sum %s")
            cmd_md5_vm = cmd_md5 % guest_file
        md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]
        error_context.context("md5 of the guest file: %s" % md5_guest, LOG_JOB.info)
        md5_host = (
            process.run("md5sum %s" % host_data, io_timeout)
            .stdout_text.strip()
            .split()[0]
        )
        error_context.context("md5 of the host file: %s" % md5_host, LOG_JOB.info)
        if md5_guest != md5_host:
            test.fail("The md5 value of host is not same to guest.")
        else:
            error_context.context(
                "The md5 of host is as same as md5 of " "guest.", LOG_JOB.info
            )
    finally:
        if not windows:
            session.cmd("rm -rf %s" % guest_file)

    create_sub_folder_test(params, session, fs_dest, fs_source)


def create_sub_folder_test(params, session, guest_dest, host_dir):
    """
    Test for creating the sub folder at the shared directory.

    :param params: Dictionary with the test parameters
    :param session: The session from guest
    :param guest_dest: The shared directory on guest
    :param host_dir: The shared directory on host
    """
    os_type = params.get("os_type")
    folder_name = params.get("sub_folder_name", "virtio_fs_folder_test")
    try:
        error_context.context(
            "Create the sub folder on shared directory " "of guest: ", LOG_JOB.info
        )
        if os_type == "linux":
            session.cmd("mkdir -p %s" % (guest_dest + "/" + folder_name + "/a"))
        else:
            fs_dest = guest_dest.replace("/", "\\")
            session.cmd("md %s" % (fs_dest + "\\" + folder_name + "\\a"))

        error_context.context(
            "Check the sub folder on shared directory " "of host: ", LOG_JOB.info
        )
        if os.path.exists(host_dir + "/" + folder_name + "/a"):
            error_context.context(
                "Find the %s on the host." % (host_dir + "/" + folder_name + "/a"),
                LOG_JOB.info,
            )
        else:
            LOG_JOB.error("Do NOT find the sub folder on the host.")
    finally:
        error_context.context(
            "Delete the sub folder on shared directory " "of guest: ", LOG_JOB.info
        )
        if os_type == "linux":
            session.cmd("rm -rf %s" % (guest_dest + "/" + folder_name))
        else:
            session.cmd("rmdir /s/q %s" % (guest_dest + "\\" + folder_name))


def install_psexec(vm):
    """
    Copying psexec.exe from host to guest.( Windows only )

    :param vm: the vm object
    :return psexec_path: the psexec path in guest
    """
    src_file = os.path.join(data_dir.get_deps_dir("psexec"), "PsExec.exe")
    dest_dir = "%systemdrive%\\"
    vm.copy_files_to(src_file, dest_dir)
    return os.path.join(dest_dir, "PsExec.exe")


def basic_io_test_via_psexec(test, params, vm, usernm, pwd):
    """
    Use psexec to do the io test( Windows only ).

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param vm: the vm object
    :param usernm: the username used to execute the cmd
    :param pwd: the password used to execute the cmd
    """
    if params.get("os_type", "windows") == "windows":
        error_context.context("Running viofs basic io test via psexec", LOG_JOB.info)
        cmd_dd_win = params.get(
            "virtio_fs_cmd_dd_win",
            "C:\\tools\\dd.exe if=/dev/random of=%s " "bs=1M count=100",
        )
        test_file = params.get("virtio_fs_test_file", "virtio_fs_test_file")
        io_timeout = params.get_numeric("fs_io_timeout", 120)
        fs_source = params.get("fs_source_dir", "virtio_fs_test/")
        fs_target = params.get("fs_target", "myfs")
        base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())
        if not os.path.isabs(fs_source):
            fs_source = os.path.join(base_dir, fs_source)
        host_data = os.path.join(fs_source, test_file)

        session = vm.wait_for_login()
        driver_letter = get_virtiofs_driver_letter(test, fs_target, session)
        fs_dest = "%s:" % driver_letter
        guest_file = os.path.join(fs_dest, test_file)
        cmd_io_test = "%systemdrive%\\cmd_io_test.bat"

        error_context.context(
            "Creating the test file(cmd_io_test.bat) " "on guest", LOG_JOB.info
        )
        session.cmd("echo " + cmd_dd_win % guest_file + " > " + cmd_io_test, io_timeout)

        psexec_path = install_psexec(vm)
        try:
            error_context.context("Execute the cmd_io_test.bat on guest", LOG_JOB.info)
            domain_dns = params.get("domain_dns", "")
            domain_dns += "\\" if domain_dns else ""
            session.cmd(
                psexec_path
                + " /accepteula -u "
                + domain_dns
                + usernm
                + " -p "
                + pwd
                + " "
                + cmd_io_test
            )

            guest_file_win = guest_file.replace("/", "\\")
            cmd_md5 = params.get("cmd_md5", "%s: && md5sum.exe %s")
            cmd_md5_vm = cmd_md5 % (driver_letter, guest_file_win)
            md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]
            error_context.context("md5 of the guest file: %s" % md5_guest, LOG_JOB.info)
            md5_host = (
                process.run("md5sum %s" % host_data, io_timeout)
                .stdout_text.strip()
                .split()[0]
            )
            error_context.context("md5 of the host file: %s" % md5_host, LOG_JOB.info)
            if md5_guest != md5_host:
                test.fail("The md5 value of host is not same to guest.")
            else:
                error_context.context(
                    "The md5 of host is as same as md5 of " "guest.", LOG_JOB.info
                )
        finally:
            error_context.context("Delete the test file from host.", LOG_JOB.info)
            os.remove(host_data)

        error_context.context("Start to test creating/deleting folder...", LOG_JOB.info)
        bat_create_folder_test = "%systemdrive%\\cmd_create_folder_test.bat"
        folder_name = params.get("sub_folder_name", "virtio_fs_folder_test")
        cmd_create_folder = "md %s" % (fs_dest + "\\" + folder_name + "\\a")
        try:
            session.cmd("echo " + cmd_create_folder + " > " + bat_create_folder_test)
            error_context.context(
                "Create the sub folder on shared directory " "of guest: ", LOG_JOB.info
            )
            session.cmd(
                psexec_path
                + " /accepteula -u "
                + domain_dns
                + usernm
                + " -p "
                + pwd
                + " "
                + bat_create_folder_test
            )
            error_context.context(
                "Check the sub folder on shared directory " "of host: ", LOG_JOB.info
            )
            if os.path.exists(fs_source + "/" + folder_name + "/a"):
                error_context.context(
                    "Find the %s on the host." % (fs_source + "/" + folder_name + "/a"),
                    LOG_JOB.info,
                )
            else:
                LOG_JOB.error("Do NOT find the sub folder on the host.")
        finally:
            error_context.context(
                "Delete the sub folder on shared directory " "of guest: ", LOG_JOB.info
            )
            session.cmd("rmdir /s /q %s" % (fs_dest + "\\" + folder_name))


def get_viofs_exe_path(test, params, session):
    """
    Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    error_context.context("Get virtiofs exe full path.", test.log.info)
    media_type = params["virtio_win_media_type"]
    try:
        get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
        get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
        get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
    except AttributeError:
        test.error("Not supported virtio win media type '%s'", media_type)
    viowin_ltr = get_drive_letter(session)
    if not viowin_ltr:
        test.error("Could not find virtio-win drive in guest")
    guest_name = get_product_dirname(session)
    if not guest_name:
        test.error("Could not get product dirname of the vm")
    guest_arch = get_arch_dirname(session)
    if not guest_arch:
        test.error("Could not get architecture dirname of the vm")

    exe_middle_path = (
        "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
    ).format(name=guest_name, arch=guest_arch)
    exe_file_name = "virtiofs.exe"
    exe_find_cmd = 'dir /b /s %s\\%s | findstr "\\%s\\\\"'
    exe_find_cmd %= (viowin_ltr, exe_file_name, exe_middle_path)
    exe_path = session.cmd(exe_find_cmd).strip()
    test.log.info("Found exe file '%s'", exe_path)
    return exe_path


def create_viofs_service(test, params, session, service="VirtioFsSvc"):
    """
    Only for windows guest, to create a virtiofs service
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    install_winfsp(test, params, session)
    exe_path = get_viofs_exe_path(test, params, session)
    viofs_exe_copy_cmd_default = "xcopy %s C:\\ /Y"
    viofs_exe_copy_cmd = params.get("viofs_exe_copy_cmd", viofs_exe_copy_cmd_default)
    if service == "VirtioFsSvc":
        error_context.context(
            "Create virtiofs own service in" " Windows guest.", test.log.info
        )
        output = query_viofs_service(test, params, session)
        if "not exist as an installed service" in output:
            session.cmd(viofs_exe_copy_cmd % exe_path)
            viofs_sc_create_cmd_default = (
                "sc create VirtioFsSvc "
                'binpath="c:\\virtiofs.exe" '
                "start=auto  "
                'depend="WinFsp.Launcher/VirtioFsDrv" '
                'DisplayName="Virtio FS Service"'
            )
            viofs_sc_create_cmd = params.get(
                "viofs_sc_create_cmd", viofs_sc_create_cmd_default
            )
            sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd)
            if sc_create_s != 0:
                test.fail(
                    "Failed to create virtiofs service, " "output is %s" % sc_create_o
                )
    if service == "WinFSP.Launcher":
        error_context.context(
            "Stop virtiofs own service, " "using WinFsp.Launcher service instead.",
            test.log.info,
        )
        stop_viofs_service(test, params, session)
        session.cmd(viofs_exe_copy_cmd % exe_path)
        error_context.context("Config WinFsp.Launcher for multifs.", test.log.info)
        output = session.cmd_output(params["viofs_sc_create_cmd"])
        if "completed successfully" not in output.lower():
            test.fail(
                "MultiFS: Config WinFsp.Launcher failed, " "the output is %s." % output
            )


def delete_viofs_serivce(test, params, session):
    """
    Delete the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_delete_cmd = params.get("viofs_sc_delete_cmd", "sc delete VirtioFsSvc")
    error_context.context("Deleting the viofs service...", test.log.info)
    output = query_viofs_service(test, params, session)
    if "not exist as an installed service" in output:
        test.log.info(
            "The viofs service was NOT found at the guest." " Skipping delete..."
        )
    else:
        status = session.cmd_status(viofs_sc_delete_cmd)
        if status == 0:
            test.log.info("Done to delete the viofs service...")
        else:
            test.error("Failed to delete the viofs service...")


def start_viofs_service(test, params, session):
    """
    Start the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_start_cmd = params.get("viofs_sc_start_cmd", "sc start VirtioFsSvc")
    error_context.context("Start the viofs service...", test.log.info)
    test.log.info("Check if virtiofs service is started.")
    output = query_viofs_service(test, params, session)
    if "RUNNING" not in output:
        status = session.cmd_status(viofs_sc_start_cmd)
        if status == 0:
            test.log.info("Done to start the viofs service.")
        else:
            test.error("Failed to start the viofs service...")
    else:
        test.log.info("Virtiofs service is running.")


def query_viofs_service(test, params, session):
    """
    Query the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    :return output: the output of cmd return
    """
    viofs_sc_query_cmd = params.get("viofs_sc_query_cmd", "sc query VirtioFsSvc")
    error_context.context("Query the status of viofs service...", test.log.info)
    return session.cmd_output(viofs_sc_query_cmd)


def run_viofs_service(test, params, session):
    """
    Run the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    create_viofs_service(test, params, session)
    start_viofs_service(test, params, session)


def stop_viofs_service(test, params, session):
    """
    Stop the virtiofs service on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    viofs_sc_stop_cmd = params.get("viofs_sc_stop_cmd", "sc stop VirtioFsSvc")
    test.log.info("Check if virtiofs service status.")
    output = query_viofs_service(test, params, session)
    if "RUNNING" in output:
        session.cmd(viofs_sc_stop_cmd)
    else:
        test.log.info("Virtiofs service isn't running.")


def install_winfsp(test, params, session):
    """
    Install the winfsp on Windows guest
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    """
    cmd_timeout = params.get_numeric("cmd_timeout", 120)
    install_path = params["install_winfsp_path"]
    check_installed_cmd = params.get(
        "check_winfsp_installed_cmd", r'dir "%s" |findstr /I winfsp'
    )
    check_installed_cmd = check_installed_cmd % install_path
    install_winfsp_cmd = r"msiexec /i WIN_UTILS:\winfsp.msi /qn"
    install_cmd = params.get("install_winfsp_cmd", install_winfsp_cmd)
    # install winfsp tool
    test.log.info("Install winfsp for windows guest.")
    installed = session.cmd_status(check_installed_cmd) == 0
    if installed:
        test.log.info("Winfsp tool is already installed.")
    else:
        install_cmd = utils_misc.set_winutils_letter(session, install_cmd)
        session.cmd(install_cmd, cmd_timeout)
        if not utils_misc.wait_for(
            lambda: not session.cmd_status(check_installed_cmd), 60
        ):
            test.error("Winfsp tool is not installed.")


def operate_debug_log(test, params, session, vm, operation):
    """
    Only for windows guest, enable or disable debug log in guest.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session of guest
    :param vm: the vm object
    :param operation: enable or disable
    :return: session
    """
    error_context.context("%s virtiofs debug log in guest." % operation, test.log.info)
    query_cmd = params.get("viofs_reg_query_cmd", r"reg query HKLM\Software\VirtIO-FS")
    ret = session.cmd_output(query_cmd)

    run_reg_cmd = []
    if operation == "enable":
        viofs_debug_enable_cmd = params["viofs_debug_enable_cmd"]
        viofs_log_enable_cmd = params["viofs_log_enable_cmd"]
        if "debugflags" not in ret.lower() or "debuglogfile" not in ret.lower():
            run_reg_cmd = [viofs_debug_enable_cmd, viofs_log_enable_cmd]
    elif operation == "disable":
        viofs_debug_delete_cmd = params["viofs_debug_delete_cmd"]
        viofs_log_delete_cmd = params["viofs_log_delete_cmd"]
        if "debugflags" in ret.lower() or "debuglogfile" in ret.lower():
            run_reg_cmd = [viofs_debug_delete_cmd, viofs_log_delete_cmd]
    else:
        test.error("Please give a right operation.")

    for reg_cmd in run_reg_cmd:
        test.log.info("Set %s ", reg_cmd)
        s, o = session.cmd_status_output(reg_cmd)
        if s:
            test.fail("Fail command: %s. Output: %s" % (reg_cmd, o))
    if run_reg_cmd:
        session = vm.reboot()
    return session
