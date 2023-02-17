import logging
import os

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_misc

LOG_JOB = logging.getLogger('avocado.test')


def get_virtiofs_driver_letter(test, fs_target, session):
    """
    Get the virtiofs driver letter( Windows guest only )

    :param test: QEMU test object
    :param fs_target: virtio fs target
    :param session: the session of guest
    :return driver_letter: the driver letter of the virtiofs
    """
    error_context.context("Get driver letter of virtio fs target, "
                          "the driver label is %s." % fs_target, LOG_JOB.info)
    driver_letter = utils_misc.get_winutils_vol(session, fs_target)
    if driver_letter is None:
        test.fail("Could not get virtio-fs mounted driver letter.")
    return driver_letter


def basic_io_test(test, params, session):
    """
    Virtio_fs basic io test. Create file on guest and then compare two md5
    values from guest and host.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param session: the session from guest
    """
    error_context.context("Running viofs basic io test", LOG_JOB.info)
    test_file = params.get('virtio_fs_test_file', "virtio_fs_test_file")
    cmd_dd = params.get("virtio_fs_cmd_dd", 'dd if=/dev/urandom of=%s bs=1M '
                                            'count=100 iflag=fullblock')
    windows = params.get("os_type", "windows") == "windows"
    io_timeout = params.get_numeric("fs_io_timeout", 120)
    fs_source = params.get("fs_source_dir", "virtio_fs_test/")
    fs_target = params.get("fs_target", "myfs")
    base_dir = params.get("fs_source_base_dir",
                          data_dir.get_data_dir())
    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    host_data = os.path.join(fs_source, test_file)
    try:
        if windows:
            driver_letter = get_virtiofs_driver_letter(test, fs_target, session)
            fs_dest = "%s:" % driver_letter
        else:
            fs_dest = params.get("fs_dest", "/mnt/" + fs_target)
        guest_file = os.path.join(fs_dest, test_file)
        error_context.context("The guest file in shared dir is %s" %
                              guest_file, LOG_JOB.info)
        error_context.context("Creating file under %s inside guest." % fs_dest,
                              LOG_JOB.info)
        session.cmd(cmd_dd % guest_file, io_timeout)

        if windows:
            guest_file_win = guest_file.replace("/", "\\")
            cmd_md5 = params.get("cmd_md5", '%s: && md5sum.exe %s')
            cmd_md5_vm = cmd_md5 % (driver_letter, guest_file_win)
        else:
            cmd_md5 = params.get("cmd_md5", 'md5sum %s')
            cmd_md5_vm = cmd_md5 % guest_file
        md5_guest = session.cmd_output(cmd_md5_vm,
                                       io_timeout).strip().split()[0]
        error_context.context("md5 of the guest file: %s" % md5_guest,
                              LOG_JOB.info)
        md5_host = process.run("md5sum %s" % host_data,
                               io_timeout).stdout_text.strip().split()[0]
        error_context.context("md5 of the host file: %s" % md5_host,
                              LOG_JOB.info)
        if md5_guest != md5_host:
            test.fail('The md5 value of host is not same to guest.')
        else:
            error_context.context("The md5 of host is as same as md5 of "
                                  "guest.", LOG_JOB.info)
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
        error_context.context("Create the sub folder on shared directory "
                              "of guest: ", LOG_JOB.info)
        if os_type == "linux":
            session.cmd("mkdir -p %s" %
                        (guest_dest + "/" + folder_name + "/a"))
        else:
            fs_dest = guest_dest.replace("/", "\\")
            session.cmd("md %s" % (fs_dest + "\\" + folder_name + "\\a"))

        error_context.context("Check the sub folder on shared directory "
                              "of host: ", LOG_JOB.info)
        if os.path.exists(host_dir + "/" + folder_name + "/a"):
            error_context.context("Find the %s on the host." %
                                  (host_dir + "/" + folder_name + "/a"),
                                  LOG_JOB.info)
        else:
            LOG_JOB.error("Do NOT find the sub folder on the host.")
    finally:
        error_context.context("Delete the sub folder on shared directory "
                              "of guest: ", LOG_JOB.info)
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
        error_context.context("Running viofs basic io test via psexec",
                              LOG_JOB.info)
        cmd_dd_win = params.get("virtio_fs_cmd_dd_win",
                                "C:\\tools\\dd.exe if=/dev/random of=%s "
                                "bs=1M count=100")
        test_file = params.get('virtio_fs_test_file', "virtio_fs_test_file")
        io_timeout = params.get_numeric("fs_io_timeout", 120)
        fs_source = params.get("fs_source_dir", "virtio_fs_test/")
        fs_target = params.get("fs_target", "myfs")
        base_dir = params.get("fs_source_base_dir",
                              data_dir.get_data_dir())
        if not os.path.isabs(fs_source):
            fs_source = os.path.join(base_dir, fs_source)
        host_data = os.path.join(fs_source, test_file)

        session = vm.wait_for_login()
        driver_letter = get_virtiofs_driver_letter(test, fs_target, session)
        fs_dest = "%s:" % driver_letter
        guest_file = os.path.join(fs_dest, test_file)
        cmd_io_test = "%systemdrive%\\cmd_io_test.bat"

        error_context.context("Creating the test file(cmd_io_test.bat) "
                              "on guest", LOG_JOB.info)
        session.cmd("echo " + cmd_dd_win % guest_file + " > " + cmd_io_test,
                    io_timeout)

        psexec_path = install_psexec(vm)
        try:
            error_context.context("Execute the cmd_io_test.bat on guest",
                                  LOG_JOB.info)
            domain_dns = params.get("domain_dns", "")
            domain_dns += "\\" if domain_dns else ""
            session.cmd(psexec_path + " /accepteula -u " + domain_dns +
                        usernm + " -p " + pwd + " " + cmd_io_test)

            guest_file_win = guest_file.replace("/", "\\")
            cmd_md5 = params.get("cmd_md5", '%s: && md5sum.exe %s')
            cmd_md5_vm = cmd_md5 % (driver_letter, guest_file_win)
            md5_guest = session.cmd_output(cmd_md5_vm,
                                           io_timeout).strip().split()[0]
            error_context.context("md5 of the guest file: %s" % md5_guest,
                                  LOG_JOB.info)
            md5_host = process.run("md5sum %s" % host_data,
                                   io_timeout).stdout_text.strip().split()[0]
            error_context.context("md5 of the host file: %s" % md5_host,
                                  LOG_JOB.info)
            if md5_guest != md5_host:
                test.fail('The md5 value of host is not same to guest.')
            else:
                error_context.context("The md5 of host is as same as md5 of "
                                      "guest.", LOG_JOB.info)
        finally:
            error_context.context("Delete the test file from host.",
                                  LOG_JOB.info)
            os.remove(host_data)

        error_context.context("Start to test creating/deleting folder...",
                              LOG_JOB.info)
        bat_create_folder_test = "%systemdrive%\\cmd_create_folder_test.bat"
        folder_name = params.get("sub_folder_name", "virtio_fs_folder_test")
        cmd_create_folder = "md %s" % (fs_dest + "\\" + folder_name + "\\a")
        try:
            session.cmd("echo " + cmd_create_folder + " > " +
                        bat_create_folder_test)
            error_context.context("Create the sub folder on shared directory "
                                  "of guest: ", LOG_JOB.info)
            session.cmd(psexec_path + " /accepteula -u " + domain_dns +
                        usernm + " -p " + pwd + " " + bat_create_folder_test)
            error_context.context("Check the sub folder on shared directory "
                                  "of host: ", LOG_JOB.info)
            if os.path.exists(fs_source + "/" + folder_name + "/a"):
                error_context.context("Find the %s on the host." %
                                      (fs_source + "/" + folder_name + "/a"),
                                      LOG_JOB.info)
            else:
                LOG_JOB.error("Do NOT find the sub folder on the host.")
        finally:
            error_context.context("Delete the sub folder on shared directory "
                                  "of guest: ", LOG_JOB.info)
            session.cmd("rmdir /s /q %s" % (fs_dest + "\\" + folder_name))
