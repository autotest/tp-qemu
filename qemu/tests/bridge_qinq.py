import os
import re
import time

from avocado.utils import crypto, process
from virttest import data_dir, env_process, error_context, remote, utils_net, utils_test
from virttest.utils_version import VersionInterval


@error_context.context_aware
def run(test, params, env):
    """
    Test basic QinQ - 10 * 4096 with bridge backend

    1) Create a private bridge
    2) Boot a VM over private bridge
    3) Create interfaces in guest with qinq.sh
    4) Set IP on guest L1 interface and bring this interface on
    5) Create 802.1ad interface on host with the private bridge
    6) Start tcpdump on host
    7) Do ping test
    8) Check tcpdump result with vlan tag and ethertype
    9) Set IP on guest L2 interface and bring this interface on
    10) Create 802.1q interface on host with the 802.1ad interface
    11) Start tcpdump on host
    12) Do ping test
    13) Check tcpdump result with vlan tag and ethertype
    14) SCP file transfer between host and guest

    :param test: KVM test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def copy_qinq_file(vm, guest_qinq_dir):
        """
        Copy qinq file from host to guest

        :param vm: guest vm
        :param guest_qinq_dir: qing script dir in guest

        """
        error_context.context("Copy qinq script to guest", test.log.info)
        host_qinq_dir = os.path.join(
            data_dir.get_deps_dir(), params.get("copy_qinq_script")
        )
        vm.copy_files_to(host_qinq_dir, guest_qinq_dir)

    def check_tcpdump_result(
        session,
        iface_name,
        ethertype,
        ethertype2=None,
        vlan_tag=None,
        vlan_tag2=None,
        enable_logging=False,
    ):
        """
        Check tcpdump result.

        :param session: guest session
        :param iface_name: the tcpdump file of the interface
        :param ethertype: ethertype value need to be matched
        :param ethertype2: ethertype value 2 needed to be matched if not None
        :param vlan_tag: vlan tag value needed to be matched if not None
        :param vlan_tag2: vlan tag value 2 needed to be matched if not None
        :param enable_logging: whether to dump tcpdump results during test
        """
        get_tcpdump_log_cmd = params["get_tcpdump_log_cmd"] % iface_name
        tcpdump_content = session.cmd_output(
            get_tcpdump_log_cmd, timeout=300, safe=True
        ).strip()
        lines = tcpdump_content.splitlines()
        sum = 0
        for i in range(len(lines)):
            if enable_logging:
                test.log.info("line %s: %s", i, lines[i])
            if not ethertype2:
                if "ICMP echo re" in lines[i] and ethertype in lines[i - 1]:
                    sum += 1
                    if vlan_tag and vlan_tag not in lines[i - 1]:
                        if "too much work for irq" in lines[i - 1]:
                            continue
                        else:
                            test.fail(
                                "in %s tcpdump log, there should be vlan "
                                "tag %s" % (iface_name, vlan_tag)
                            )
                    elif not vlan_tag:
                        if "vlan" in lines[i - 1]:
                            test.fail(
                                "in %s tcpdump log, there should not be "
                                "vlan tag" % iface_name
                            )
            else:
                if (
                    "ICMP echo re" in lines[i]
                    and ethertype in lines[i - 1]
                    and ethertype2 in lines[i - 1]
                ):
                    sum += 1
                    if vlan_tag not in lines[i - 1] or vlan_tag2 not in lines[i - 1]:
                        if "too much work for irq" in lines[i - 1]:
                            continue
                        else:
                            test.fail(
                                "in %s tcpdump log, there should be vlan "
                                "tag %s" % (iface_name, vlan_tag)
                            )
        if sum == 0:
            test.fail(
                "in %s tcpdump log, ethertype is not %s" % (iface_name, ethertype)
            )

    def compare_host_guest_md5sum():
        """
        Compare md5 value of file on host and guest

        :param name: file name

        """
        test.log.info("Comparing md5sum on guest and host")
        host_result = crypto.hash_file(host_path, algorithm="md5")
        try:
            output = session.cmd_output("md5sum %s" % guest_path, 120).split()[0]
            guest_result = re.findall(r"\w+", output)[0]
        except IndexError:
            test.log.error("Could not get file md5sum in guest")
            return False
        test.log.debug("md5sum: guest(%s), host(%s)", guest_result, host_result)
        return guest_result == host_result

    if params["netdst"] not in utils_net.Bridge().list_br():
        test.cancel("Only support Linux bridge")

    login_timeout = int(params.get("login_timeout", "600"))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    guest_qinq_dir = params["guest_qinq_dir"]
    copy_qinq_file(vm, guest_qinq_dir)
    session.close()
    vm.destroy(gracefully=True)

    brname = params.get("private_bridge", "tmpbr")
    host_bridges = utils_net.Bridge()
    if brname in host_bridges.list_br():
        utils_net.Interface(brname).down()
        host_bridges.del_bridge(brname)

    set_ip_cmd = params["set_ip_cmd"]
    test.log.debug("Create private bridge %s", brname)
    host_bridges.add_bridge(brname)
    host_bridge_iface = utils_net.Interface(brname)
    test.log.debug("Bring up %s", brname)
    process.system(set_ip_cmd % ("192.168.1.1", brname))
    host_bridge_iface.up()

    file_size = int(params.get("file_size", "4096"))
    host_path = os.path.join(test.tmpdir, "transferred_file")
    guest_path = params.get("guest_path", "/var/tmp/transferred_file")
    transfer_timeout = int(params.get("transfer_timeout", 1000))

    try:
        login_timeout = int(params.get("login_timeout", "600"))
        params["netdst"] = brname
        params["start_vm"] = "yes"
        params["image_snapshot"] = "yes"
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        session = vm.wait_for_serial_login(timeout=login_timeout)
        stop_NM_cmd = params.get("stop_NM_cmd")
        session.cmd(stop_NM_cmd, ignore_all_errors=True)
        mac = vm.get_mac_address()
        nic_name = utils_net.get_linux_ifname(session, mac)

        # Set first_nic IP in guest
        ip = params["ip_vm"]
        session.cmd_output(set_ip_cmd % (ip, nic_name))

        # Create vlans via script qinq.sh
        output = session.cmd_output(
            "sh %sqinq.sh %s" % (guest_qinq_dir, nic_name), timeout=300
        )
        test.log.info("%s", output)

        # Set interface v1v10 IP in guest
        L1tag_iface = params["L1tag_iface"]
        L1tag_iface_ip = params["L1tag_iface_ip"]
        session.cmd_output(set_ip_cmd % (L1tag_iface_ip, L1tag_iface))
        session.cmd("ip link set %s up" % L1tag_iface)
        output = session.cmd_output("ip addr show %s" % L1tag_iface, timeout=120)
        test.log.info(output)

        # Start tcpdump on L1tag interface and first_nic in guest
        error_context.context("Start tcpdump in %s" % params["main_vm"], test.log.info)
        L1tag_tcpdump_log = params.get("tcpdump_log") % L1tag_iface
        L1tag_tcpdump_cmd = params.get("tcpdump_cmd") % (L1tag_iface, L1tag_tcpdump_log)
        first_nic_tcpdump_log = params.get("tcpdump_log") % nic_name
        first_nic_tcpdump_cmd = params.get("tcpdump_cmd") % (
            nic_name,
            first_nic_tcpdump_log,
        )
        session.sendline(L1tag_tcpdump_cmd)
        time.sleep(2)
        session.sendline(first_nic_tcpdump_cmd)
        time.sleep(5)

        # Create 802.1ad vlan via bridge in host
        error_context.context(
            "Create 802.1ad vlan via bridge %s" % brname, test.log.info
        )
        advlan_ifname = params["advlan_name"]
        add_advlan_cmd = params["add_advlan_cmd"]
        process.system_output(add_advlan_cmd)
        advlan_iface = utils_net.Interface(advlan_ifname)
        advlan_iface.set_mac(params["advlan_mac"])
        process.system(set_ip_cmd % (params["advlan_ip"], advlan_ifname))
        advlan_iface.up()
        output = process.getoutput("ip addr show %s" % advlan_ifname)
        test.log.info(output)

        # Ping guest from host via 802.1ad vlan interface
        error_context.context(
            "Start ping test from host to %s via %s" % (L1tag_iface_ip, advlan_ifname),
            test.log.info,
        )
        ping_count = int(params.get("ping_count"))
        status, output = utils_net.ping(
            L1tag_iface_ip,
            ping_count,
            interface=advlan_ifname,
            timeout=float(ping_count) * 1.5,
        )
        if status != 0:
            test.fail("Ping returns non-zero value %s" % output)
        package_lost = utils_test.get_loss_ratio(output)
        if package_lost != 0:
            test.fail(
                "%s packeage lost when ping guest ip %s "
                % (package_lost, L1tag_iface_ip)
            )

        # Stop tcpdump and check result
        session.cmd_output_safe("pkill tcpdump")
        check_tcpdump_result(session, L1tag_iface, "ethertype IPv4 (0x0800)")
        check_tcpdump_result(
            session, nic_name, "ethertype 802.1Q-QinQ (0x88a8)", vlan_tag="vlan 10,"
        )

        # Set IP on L2 tag on the guest interface with vid 20
        L2tag_iface = params["L2tag_iface"]
        L2tag_iface_ip = params["L2tag_iface_ip"]
        session.cmd_output(set_ip_cmd % (L2tag_iface_ip, L2tag_iface))
        session.cmd("ip link set %s up" % L2tag_iface)
        output = session.cmd_output("ip addr show %s" % L2tag_iface, timeout=120)
        test.log.info(output)

        # Start tcpdump on L1tag and L2tag interfaces and first_nic in guest
        error_context.context("Start tcpdump in %s" % params["main_vm"], test.log.info)
        L2tag_tcpdump_log = params.get("tcpdump_log") % L2tag_iface
        L2tag_tcpdump_cmd = params.get("tcpdump_cmd") % (L2tag_iface, L2tag_tcpdump_log)
        session.sendline(L1tag_tcpdump_cmd)
        time.sleep(2)
        session.sendline(L2tag_tcpdump_cmd)
        time.sleep(2)
        session.sendline(first_nic_tcpdump_cmd)
        time.sleep(5)

        # Create 802.1q vlan via 802.1ad vlan in host
        error_context.context(
            "Create 802.1q vlan via 802.1ad vlan %s" % advlan_ifname, test.log.info
        )
        qvlan_ifname = params["qvlan_name"]
        add_qvlan_cmd = params["add_qvlan_cmd"]
        process.system_output(add_qvlan_cmd)
        qvlan_iface = utils_net.Interface(qvlan_ifname)
        process.system(set_ip_cmd % (params["qvlan_ip"], qvlan_ifname))
        qvlan_iface.up()
        output = process.getoutput("ip addr show %s" % qvlan_ifname)
        test.log.info(output)

        # Ping guest from host via 802.1q vlan interface
        error_context.context(
            "Start ping test from host to %s via %s" % (L2tag_iface_ip, qvlan_ifname),
            test.log.info,
        )
        status, output = utils_net.ping(
            L2tag_iface_ip,
            ping_count,
            interface=qvlan_ifname,
            timeout=float(ping_count) * 1.5,
        )
        if status != 0:
            test.fail("Ping returns non-zero value %s" % output)
        package_lost = utils_test.get_loss_ratio(output)
        if package_lost >= 5:
            test.fail(
                "%s packeage lost when ping guest ip %s "
                % (package_lost, L2tag_iface_ip)
            )

        # Stop tcpdump and check result
        session.cmd_output_safe("pkill tcpdump")
        check_tcpdump_result(
            session, L1tag_iface, "ethertype 802.1Q (0x8100)", vlan_tag="vlan 20,"
        )
        check_tcpdump_result(session, L2tag_iface, "ethertype IPv4 (0x0800)")
        check_tcpdump_result(
            session,
            nic_name,
            ethertype="ethertype 802.1Q-QinQ (0x88a8)",
            ethertype2="ethertype 802.1Q",
            vlan_tag="vlan 10,",
            vlan_tag2="vlan 20,",
        )

        # configure the outer VLAN MTU to 1504 on qemu-8.1
        if (
            vm.devices.qemu_version in VersionInterval("[8.1.0,)")
            and params.get("nic_model") == "e1000e"
        ):
            session.cmd("ip link set %s mtu 1504" % nic_name)

        # scp file to guest with L2 vlan tag
        cmd = "dd if=/dev/zero of=%s bs=1M count=%d" % (host_path, file_size)
        error_context.context("Creating %dMB file on host" % file_size, test.log.info)
        process.run(cmd)
        error_context.context(
            "Transferring file host -> guest, " "timeout: %ss" % transfer_timeout,
            test.log.info,
        )
        shell_port = int(params.get("shell_port", 22))
        password = params["password"]
        username = params["username"]
        remote.scp_to_remote(
            L2tag_iface_ip, shell_port, username, password, host_path, guest_path
        )
        if not compare_host_guest_md5sum():
            test.fail("md5sum mismatch on guest and host")
    finally:
        session.cmd("rm -rf %s" % guest_path)
        session.close()
        vm.destroy(gracefully=False)
        host_bridge_iface.down()
        host_bridges.del_bridge(brname)
