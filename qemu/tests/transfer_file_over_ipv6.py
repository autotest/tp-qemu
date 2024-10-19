import os
import random
import re

from avocado.utils import crypto, process
from virttest import error_context, remote, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test Step
        1. boot up two virtual machine
        2. For linux guest,Transfer data:
              host <--> guest1 <--> guest2 <-->host via ipv6
           For windows guest,Transfer data:
              host <--> guest1&guest2 via ipv6
        3. after data transfer, check data have no change
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """
    timeout = int(params.get("login_timeout", "360"))
    client = params.get("file_transfer_client")
    port = params.get("file_transfer_port")
    password = params.get("password")
    username = params.get("username")
    tmp_dir = params["tmp_dir"]
    filesize = int(params.get("filesize", "4096"))
    dd_cmd = params["dd_cmd"]
    file_trans_timeout = int(params.get("file_trans_timeout", "1200"))
    file_md5_check_timeout = int(params.get("file_md5_check_timeout", "600"))
    link_local_ipv6_addr = params.get_boolean("link_local_ipv6_addr")
    netid = params.get("netid", "2620:2023:09:12")

    def get_file_md5sum(file_name, session, timeout):
        """
        Get file md5sum from guest.
        """
        test.log.info("Get md5sum of the file:'%s'", file_name)
        s, o = session.cmd_status_output("md5sum %s" % file_name, timeout=timeout)
        if s != 0:
            test.error("Get file md5sum failed as %s" % o)
        return re.findall(r"\w{32}", o)[0]

    sessions = {}
    addresses = {}
    inet_name = {}
    vms = []

    error_context.context("Boot vms for test", test.log.info)
    for vm_name in params.get("vms", "vm1 vm2").split():
        vms.append(env.get_vm(vm_name))

    # config ipv6 address host and guest.
    nettype = params.get("nettype", "vdpa")
    if nettype == "vdpa":
        host_ifname = params.get("netdst")
        hostid = random.randint(31, 50)
        process.run(
            "ip addr add %s::%s/64 dev %s" % (netid, hostid, host_ifname),
            ignore_status=True,
        )
    else:
        host_ifname = params.get("netdst") if link_local_ipv6_addr else None
    host_address = utils_net.get_host_ip_address(
        params, ip_ver="ipv6", linklocal=link_local_ipv6_addr
    )

    error_context.context("Get ipv6 address of host: %s" % host_address, test.log.info)
    for vm in vms:
        vm.verify_alive()
        sessions[vm] = vm.wait_for_login(timeout=timeout)
        if params.get("os_type") == "linux":
            inet_name[vm] = utils_net.get_linux_ifname(
                sessions[vm], vm.get_mac_address()
            )
        if nettype == "vdpa":
            guestid = random.randint(1, 30)
            sessions[vm].cmd(
                "ip addr add %s::%s/64 dev %s" % (netid, guestid, inet_name[vm]),
                timeout=timeout,
                ignore_all_errors=True,
            )
            addresses[vm] = utils_net.get_guest_ip_addr(
                sessions[vm],
                vm.get_mac_address(),
                params.get("os_type"),
                ip_version="ipv6",
                linklocal=link_local_ipv6_addr,
            )
        else:
            addresses[vm] = utils_net.get_guest_ip_addr(
                sessions[vm],
                vm.get_mac_address(),
                params.get("os_type"),
                ip_version="ipv6",
                linklocal=link_local_ipv6_addr,
            )
            if link_local_ipv6_addr is False and addresses[vm] is None:
                test.cancel("Your guest can not get remote IPv6 address.")
            error_context.context(
                "Get ipv6 address of %s: %s" % (vm.name, addresses[vm]), test.log.info
            )

    # prepare test data
    guest_path = tmp_dir + "src-%s" % utils_misc.generate_random_string(8)
    dest_path = tmp_dir + "dst-%s" % utils_misc.generate_random_string(8)
    host_path = os.path.join(
        test.tmpdir, "tmp-%s" % utils_misc.generate_random_string(8)
    )
    test.log.info("Test setup: Creating %dMB file on host", filesize)
    process.run(dd_cmd % (host_path, filesize), shell=True)

    try:
        src_md5 = crypto.hash_file(host_path, algorithm="md5")
        error_context.context("md5 value of data from src: %s" % src_md5, test.log.info)
        # transfer data
        for vm in vms:
            error_context.context(
                "Transfer data from host to %s" % vm.name, test.log.info
            )
            remote.copy_files_to(
                addresses[vm],
                client,
                username,
                password,
                port,
                host_path,
                guest_path,
                timeout=file_trans_timeout,
                interface=host_ifname,
            )
            dst_md5 = get_file_md5sum(
                guest_path, sessions[vm], timeout=file_md5_check_timeout
            )
            error_context.context(
                "md5 value of data in %s: %s" % (vm.name, dst_md5), test.log.info
            )
            if dst_md5 != src_md5:
                test.fail("File changed after transfer host -> %s" % vm.name)

        if params.get("os_type") == "linux":
            for vm_src in addresses:
                for vm_dst in addresses:
                    if vm_src != vm_dst:
                        error_context.context(
                            "Transferring data from %s to %s"
                            % (vm_src.name, vm_dst.name),
                            test.log.info,
                        )
                        if params.get_boolean("using_guest_interface"):
                            dst_interface = inet_name[vm_src]
                        else:
                            dst_interface = host_ifname
                        remote.scp_between_remotes(
                            addresses[vm_src],
                            addresses[vm_dst],
                            port,
                            password,
                            password,
                            username,
                            username,
                            guest_path,
                            dest_path,
                            timeout=file_trans_timeout,
                            src_inter=host_ifname,
                            dst_inter=dst_interface,
                        )
                        dst_md5 = get_file_md5sum(
                            dest_path, sessions[vm_dst], timeout=file_md5_check_timeout
                        )
                        error_context.context(
                            "md5 value of data in %s: %s" % (vm.name, dst_md5),
                            test.log.info,
                        )
                        if dst_md5 != src_md5:
                            test.fail(
                                "File changed transfer %s -> %s"
                                % (vm_src.name, vm_dst.name)
                            )

        for vm in vms:
            error_context.context(
                "Transfer data from %s to host" % vm.name, test.log.info
            )
            remote.copy_files_from(
                addresses[vm],
                client,
                username,
                password,
                port,
                guest_path,
                host_path,
                timeout=file_trans_timeout,
                interface=host_ifname,
            )
            error_context.context(
                "Check whether the file changed after trans", test.log.info
            )
            dst_md5 = crypto.hash_file(host_path, algorithm="md5")
            error_context.context(
                "md5 value of data after copying to host: %s" % dst_md5, test.log.info
            )

            if dst_md5 != src_md5:
                test.fail("File changed after transfer (md5sum mismatch)")
            process.system_output("rm -rf %s" % host_path, timeout=timeout)

    finally:
        process.system("rm -rf %s" % host_path, timeout=timeout, ignore_status=True)
        if nettype == "vdpa":
            process.run("ip addr del %s/64 dev %s" % (host_address, host_ifname))
        for vm in vms:
            if params.get("os_type") == "linux":
                sessions[vm].cmd(
                    "rm -rf %s %s || true" % (guest_path, dest_path),
                    timeout=timeout,
                    ignore_all_errors=True,
                )
            else:
                sessions[vm].cmd(
                    "del /f %s" % guest_path, timeout=timeout, ignore_all_errors=True
                )
            sessions[vm].close()
