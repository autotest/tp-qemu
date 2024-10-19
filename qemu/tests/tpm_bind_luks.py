import re

from virttest import error_context, utils_disk, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    Verify the TPM device can automatically unlock the LUKs device.
    Steps:
        1. Format the extra disk to LUKs via cryptsetup
        2. Open the LUKs disk, mount it and create a file system
        3. Bind the extra disk using the TPM2 policy
        4. Open the LUKs device via clevis and check the file's md5
        5. Modify crypttab and fstab to enable automatic boot unlocking
        6. Reboot guest and check if OS can unlock the LUKs FS automatically

    :param test: QEMU test object.
    :type  test: avocado.core.test.Test
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """

    def mount_disk(file_func):
        """
        Mount and umount the disk before and after operate a file.

        :param file_func: function to handle the random file in the LUKs volume
        :type file_func: file_func
        """

        def wrapper(*args, **kwargs):
            if not utils_disk.is_mount(mapper_dev, mount_path, session=session):
                test.log.info("Mount the LUKs FS...")
                if not utils_disk.mount(mapper_dev, mount_path, session=session):
                    test.error("Cannot mount %s to %s" % (mapper_dev, mount_path))
            out = file_func(*args, **kwargs)
            test.log.info("Umount the LUKs FS...")
            if not utils_disk.umount(mapper_dev, mount_path, session=session):
                test.error("Cannot umount " + mount_path)
            return out

        return wrapper

    def get_md5sum():
        """
        Return the file's MD5
        """
        status, md5 = session.cmd_status_output(
            "md5sum " + dd_file, print_func=test.log.info
        )
        if status:
            test.error("Failed to get file's MD5")
        return md5.split()[0]

    @mount_disk
    def create_random_file():
        """
        Create a file with random data and return it's MD5
        """
        test.log.info("Create a random file...")
        session.cmd(dd_cmd)
        return get_md5sum()

    @mount_disk
    def compare_md5sum():
        """
        Compare the current MD5 value with the original one
        """
        md5_current = get_md5sum()
        if md5_current != md5_original:
            test.fail(
                "File %s changed, the current md5(%s) is mismatch of the"
                " original md5(%s)" % (dd_file, md5_current, md5_original)
            )
        test.log.info("File's md5 matched, md5: %s", md5_current)

    @mount_disk
    def auto_boot_unlocking():
        """
        Steps to configure automatic unlocking at late boot stage
        """
        disk_uuid = session.cmd_output("blkid -s UUID -o value %s" % extra_disk).strip()
        session.cmd(
            'echo "%s UUID=%s none tpm2-device=auto" >> /etc/crypttab'
            % (mapper_name, disk_uuid)
        )
        session.cmd(
            'echo "%s %s xfs defaults 0 0" >> /etc/fstab' % (mapper_dev, mount_path)
        )
        session.cmd("restorecon -Rv " + mount_path)
        s, o = session.cmd_status_output("mount -av")
        if s != 0:
            test.fail("Mount format is incorrect:\n%s" % o)
        test.log.debug("The full mount list is:\n%s", o)
        session.cmd("systemctl enable clevis-luks-askpass.path")

    clevis_bind_cmd = params["clevis_bind_cmd"]
    clevis_list_cmd = params["clevis_list_cmd"]
    clevis_unlock_cmd = params["clevis_unlock_cmd"]
    cryptsetup_check_cmd = params["cryptsetup_check_cmd"]
    cryptsetup_close_cmd = params["cryptsetup_close_cmd"]
    cryptsetup_format_cmd = params["cryptsetup_format_cmd"]
    cryptsetup_open_cmd = params["cryptsetup_open_cmd"]
    dd_cmd = params["dd_cmd"]
    dd_file = params["dd_file"]
    mapper_dev = params["mapper_dev"]
    mapper_name = params["mapper_name"]
    mount_path = params.get("mount_path", "/mnt")
    pcr_policy = params["pcr_policy"]
    required_packages = params.objects("required_pkgs")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    extra_disk = "/dev/" + list(utils_disk.get_linux_disks(session).keys())[0]

    test.log.info("Install required packages in VM")
    if not utils_package.package_install(required_packages, session):
        test.cancel("Cannot install required packages in VM")

    error_context.base_context("Format the extra disk to LUKs", test.log.info)
    session.cmd(cryptsetup_format_cmd % extra_disk)
    test.log.info("Check if the extra disk is LUKs format")
    if session.cmd_status(cryptsetup_check_cmd + extra_disk) != 0:
        test.fail("The extra disk cannot be formatted to LUKs")
    test.log.debug(
        "The extra disk is formatted to LUKs:\n%s",
        session.cmd_output("cryptsetup luksDump " + extra_disk),
    )

    error_context.context("Open the LUKs disk", test.log.info)
    session.cmd(cryptsetup_open_cmd % extra_disk)
    session.cmd("mkfs.xfs -f " + mapper_dev)
    test.log.info("A new xfs file system is created for %s", mapper_dev)

    error_context.context("Mount the FS and create a random file", test.log.info)
    if session.cmd_status("test -d " + mount_path) != 0:
        session.cmd("mkdir -p " + mount_path)
    md5_original = create_random_file()
    session.cmd(cryptsetup_close_cmd)

    test.log.info("Reset TPM DA lockout counter before binding")
    session.cmd("tpm2_dictionarylockout --clear-lockout")
    error_context.base_context(
        "Bind %s using the TPM2 policy" % extra_disk, test.log.info
    )
    session.cmd(clevis_bind_cmd % extra_disk)
    clevis_list = session.cmd_output(clevis_list_cmd + extra_disk)
    if not re.search(r"tpm2 \S+%s" % pcr_policy, clevis_list, re.M):
        test.fail("Failed to bind the disk with TPM2 policy via clevis")
    test.log.info("The LUKs device is bound to TPM:\n%s", clevis_list)

    error_context.context(
        "Open the LUKs device using clevis and check the md5" " of the file",
        test.log.info,
    )
    session.cmd(clevis_unlock_cmd % extra_disk)
    compare_md5sum()

    error_context.context(
        "Modify crypttab and fstab to enable automatic boot " "unlocking", test.log.info
    )
    auto_boot_unlocking()
    session.cmd(cryptsetup_close_cmd)

    error_context.context(
        "Reboot the guest to check if the operating system "
        "can unlock the LUKs FS automatically"
    )
    session = vm.reboot(session)
    compare_md5sum()
