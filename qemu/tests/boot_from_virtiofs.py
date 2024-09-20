import os

from avocado.utils import process
from virttest import data_dir, env_process


def create_kernel_initrd(test, params):
    """
    Create initramfs and kernel file with dracut modul

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    """
    test.log.info("Creating initramfs and kernel file")
    install_path = data_dir.get_data_dir()
    kernel_version = process.getoutput(params.get("guest_ver_cmd", "uname -r"))
    create_initramfs_cmd = params["create_initramfs_cmd"] % install_path
    status, output = process.getstatusoutput(create_initramfs_cmd)
    if status:
        test.fail("Failed to create initramfs.")
    test.log.info("initramfs is created in %s", install_path)
    initrd_path = install_path + "/initramfs-virtiofs.img"

    # copy vmlinuz to virtiofs_root
    process.system("cp /boot/vmlinuz-%s %s" % (kernel_version, install_path))
    kernel_path = install_path + ("/vmlinuz-%s" % kernel_version)
    params["kernel"] = kernel_path
    params["initrd"] = initrd_path
    return [kernel_path, initrd_path]


def setup_basic_root_fs(test, params):
    """
    create basic root file system

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    """
    test.log.info("Setting basic root file system")
    virtiofs_root_path = data_dir.get_data_dir() + "/virtiofs_root"
    install_file_system_cmd = params["install_file_system_cmd"] % virtiofs_root_path
    status, output = process.getstatusoutput(install_file_system_cmd)
    if status:
        test.fail(
            "Failed to install basic root file system." "Error message: %s" % output
        )
    return virtiofs_root_path


def change_fs_passwd(test, params, virtiofs_root_path):
    """
    change the password

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :paran virtiofs_root_path: String of virtiofs system path
    """
    test.log.info("Changing password of the virtiofs")
    check_selinux_cmd = params["check_selinux_cmd"]
    original_selinux_value = process.getoutput(check_selinux_cmd)
    if original_selinux_value != "Disabled":
        process.getoutput("setenforce 0")

    set_passwd_cmd = params["set_passwd_cmd"]
    fd = os.open("/", os.R_OK, os.X_OK)
    # change root path
    os.chroot(virtiofs_root_path)
    # change password
    os.system(set_passwd_cmd)
    os.fchdir(fd)
    os.chroot(".")

    # restore the value after change password
    if original_selinux_value != "Disabled":
        process.getoutput("setenforce 1")


def boot_from_virtiofs(test, params, env):
    """
    generate qemu cmd line and start the vm

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    test.log.info("Starting VM")
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    session = vm.wait_for_serial_login(username="root", password=params["fs_passwd"])
    if not session.is_responsive():
        test.error("Log in failed")


def clean_env(test, trash_files):
    """
    remove the files that generate by this script

    :param test:   QEMU test object.
    :param trash_files: List with the trash files path.
    """
    if trash_files:
        for file_path in trash_files:
            test.log.info("Removing file %s", file_path)
            s, o = process.getstatusoutput("rm -rf %s" % file_path)
            if s:
                test.fail("Failed to remove file %s" % file_path)


def run(test, params, env):
    """
    Boot vm from virtiofs test

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """
    try:
        trash_files = []
        virtiofs_root_path = setup_basic_root_fs(test, params)
        trash_files.append(virtiofs_root_path)
        trash_files.extend(create_kernel_initrd(test, params))
        change_fs_passwd(test, params, virtiofs_root_path)
        boot_from_virtiofs(test, params, env)
    finally:
        clean_env(test, trash_files)
