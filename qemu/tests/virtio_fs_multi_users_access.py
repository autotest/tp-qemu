from virttest import error_context, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Different users access the shared directory.

    1) Create a shared directory for testing on the host.
    2) Run the virtiofsd daemon on the host.
    3) Boot a guest on the host.
    4) Log into guest and create a new user. For AD account test,
        please join in the AD server.
    5) If guest is windows, start the viofs service and reboot.
    6) If the guest is linux, mount the file system and change model to 777.
    7) Login users, then run the basic io test and folder accessing test.
    8) After test, clear the environment.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def get_eth_name(session):
        """
        Get the ethernet adapter name that can access to AD server.

        :param session: the session of guest
        :return eth_name: the name of ethernet adapter
        """
        error_context.context("Get the ip config from guest.", test.log.info)
        ipconfig_output = session.cmd_output("ipconfig /all")
        match = "Connection-specific DNS Suffix  . : %s" % domain_dns
        if match not in ipconfig_output:
            test.error("There is NOT related domain adapter found!")
        eth_name = (
            ipconfig_output.split(match)[0].split("Ethernet adapter ")[-1].split(":")[0]
        )
        return eth_name

    def switch_dynamic_ip_to_static_ip(session, eth_name):
        """
        Assign a static IP address for the adaptor that
        can connect to the AD server.

        :param session: the session of guest
        """
        error_context.context("Get the config of %s." % eth_name, test.log.info)
        net = session.cmd_output('netsh interface ip show config name="%s"' % eth_name)

        ipaddr, gateway, _dns_server, subnet_mask = "", "", "", ""
        for line in net.splitlines():
            if "IP Address: " in line:
                ipaddr = line.split(":")[-1].lstrip()
            elif "Default Gateway:" in line:
                gateway = line.split(":")[-1].lstrip()
            elif "Subnet Prefix:" in line:
                subnet_mask = line.split("mask")[-1].lstrip()[:-1]
        error_context.context(
            "The config will be set to ipaddress:%s, "
            "gateway:%s, subnet mask:%s." % (ipaddr, gateway, subnet_mask),
            test.log.info,
        )

        ip_cmd = (
            'netsh interface ip set address name="%s" source=static '
            "addr=%s mask=%s gateway=%s" % (eth_name, ipaddr, subnet_mask, gateway)
        )
        session.cmd(ip_cmd)

        dns_cmd = (
            'netsh interface ip set dnsservers "%s" static '
            "192.168.0.1 primary" % eth_name
        )
        session.cmd(dns_cmd)

    def switch_ip_to_dynamic(session, eth_name):
        if eth_name:
            restore_ip_cmd = (
                'netsh interface ip set address name="%s" ' "source=dhcp" % eth_name
            )
            session.cmd(restore_ip_cmd)
            restore_dns_cmd = (
                'netsh interface ip set dnsservers name="%s" ' "source=dhcp" % eth_name
            )
            session.cmd(restore_dns_cmd)

    add_user_cmd = params.get("add_user_cmd")
    del_user_cmd = params.get("del_user_cmd")
    driver_name = params.get("driver_name")
    fs_target = params.get("fs_target")
    fs_dest = params.get("fs_dest")
    os_type = params.get("os_type")
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    username = params.objects("new_user")
    pwd = params.objects("new_pwd")
    domain_dns = params.get("domain_dns")
    eth_name = ""

    try:
        if not domain_dns:
            error_context.context("Create the user(s) on guest...", test.log.info)
            for _username, _pwd in zip(username, pwd):
                if os_type == "windows":
                    status = session.cmd_status(add_user_cmd % (_username, _pwd))
                else:
                    status = session.cmd_status(add_user_cmd % (_pwd, _username))
                if status != 0:
                    test.fail("Failed to create user!")

        if os_type == "windows":
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name
            )
            virtio_fs_utils.run_viofs_service(test, params, session)
            vm.reboot(session)
        else:
            error_context.context(
                "Create a destination directory %s " "inside guest." % fs_dest,
                test.log.info,
            )
            if not utils_misc.make_dirs(fs_dest, session=session):
                test.fail("Creating directory was failed!")
            error_context.context(
                "Mount virtiofs target %s to %s inside"
                " guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                test.fail("Mount virtiofs target failed.")
            error_context.context("Set 777 permission for all users.", test.log.info)
            session.cmd("chmod -R 777 %s" % fs_dest)

        for _username, _pwd in zip(username, pwd):
            try:
                if not domain_dns:
                    error_context.context(
                        "Login the user: %s" % _username, test.log.info
                    )
                    session = vm.wait_for_login(username=_username, password=_pwd)
                else:
                    session = vm.wait_for_login()
                    eth_name = get_eth_name(session)
                    switch_dynamic_ip_to_static_ip(session, eth_name)
                    join_domain_cmd = params.get("join_domain")
                    join_domain_cmd = join_domain_cmd.replace("%s", _username, 1)
                    join_domain_cmd = join_domain_cmd.replace("%s", _pwd, 1)
                    error_context.context("Join domain...", test.log.info)
                    output = session.cmd_output(join_domain_cmd)
                    if "does not exist" in output:
                        test.fail("Failed to join the domain!")
                    elif "is not recognized as an internal" in output:
                        error_context.context(
                            "The netdom is NOT supported, "
                            "trying to use powershell...",
                            test.log.info,
                        )
                        ps_cred = params.get("ps_cred")
                        ps_join_domain = params.get("ps_join_domain")
                        ps_cred = ps_cred % (_username, _pwd)
                        ps_join_domain = ps_cred + ps_join_domain
                        session.cmd('powershell "' + ps_join_domain + '"')
                    session = vm.reboot(session)

                if os_type == "windows":
                    virtio_fs_utils.basic_io_test_via_psexec(
                        test, params, vm, _username, _pwd
                    )
                else:
                    virtio_fs_utils.basic_io_test(test, params, session)
            finally:
                if domain_dns:
                    error_context.context("Remove domain...", test.log.info)
                    remove_domain_cmd = params.get("remove_domain")
                    remove_domain_cmd = remove_domain_cmd.replace("%s", _username, 1)
                    remove_domain_cmd = remove_domain_cmd.replace("%s", _pwd, 1)
                    session = vm.wait_for_login()
                    output = session.cmd_output(remove_domain_cmd)
                    if "is not recognized as an internal" in output:
                        error_context.context(
                            "The netdom is NOT supported, "
                            "trying to use powershell...",
                            test.log.info,
                        )
                        ps_cred = params.get("ps_cred")
                        ps_remove_domain = params.get("ps_remove_domain")
                        ps_cred = ps_cred % (_username, _pwd)
                        ps_remove_domain = ps_cred + ps_remove_domain
                        session.cmd('powershell "' + ps_remove_domain + '"')
                    vm.reboot(session)
    finally:
        session = vm.wait_for_login()
        if os_type == "linux":
            error_context.context("Umount and remove dir...")
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
        if not domain_dns:
            error_context.context("Delete the user(s) on guest...", test.log.info)
            for _username in username:
                output = session.cmd_output(del_user_cmd % _username)
                if "is currently used by process" in output:
                    error_context.context(
                        "Kill process before delete user...", test.log.info
                    )
                    pid = output.split(" ")[-1]
                    session.cmd("kill -9 %s" % pid)
        else:
            switch_ip_to_dynamic(session, eth_name)
        session.close()
