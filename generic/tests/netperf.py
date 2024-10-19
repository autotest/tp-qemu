import logging
import os
import re
import threading
import time

from avocado.utils import process
from virttest import error_context, remote, utils_misc, utils_net, utils_test, virt_vm

from provider import netperf_base, win_driver_utils

LOG_JOB = logging.getLogger("avocado.test")

_netserver_started = False


def start_netserver_win(session, start_cmd, test):
    check_reg = re.compile(r"NETSERVER.*EXE", re.I)
    if not check_reg.findall(session.cmd_output("tasklist")):
        session.sendline(start_cmd)
        if not utils_misc.wait_for(
            lambda: check_reg.findall(session.cmd_output("tasklist")),
            30,
            5,
            1,
            "Wait netserver start",
        ):
            msg = "Can not start netserver with command %s" % start_cmd
            test.fail(msg)


@error_context.context_aware
def run(test, params, env):
    """
    Network stress test with netperf.

    1) Boot up VM(s), setup SSH authorization between host
       and guest(s)/external host
    2) Prepare the test environment in server/client/host
    3) Execute netperf tests, collect and analyze the results

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def mtu_set(mtu):
        """
        Set server/client/host's mtu

        :param mtu: mtu value to be set
        """

        server_mtu_cmd = params.get("server_mtu_cmd")
        client_mtu_cmd = params.get("client_mtu_cmd")
        host_mtu_cmd = params.get("host_mtu_cmd")
        error_context.context("Changing the MTU of guest", test.log.info)
        if params.get("os_type") == "linux":
            ethname = utils_net.get_linux_ifname(server_ctl, mac)
            netperf_base.ssh_cmd(server_ctl, server_mtu_cmd % (ethname, mtu))
        elif params.get("os_type") == "windows":
            connection_id = utils_net.get_windows_nic_attribute(
                server_ctl, "macaddress", mac, "netconnectionid"
            )
            netperf_base.ssh_cmd(server_ctl, server_mtu_cmd % (connection_id, mtu))

        error_context.context("Changing the MTU of client", test.log.info)
        netperf_base.ssh_cmd(
            client, client_mtu_cmd % (params.get("client_physical_nic"), mtu)
        )

        netdst = params.get("netdst", "switch")
        host_bridges = utils_net.Bridge()
        br_in_use = host_bridges.list_br()
        target_ifaces = []
        if netdst in br_in_use:
            ifaces_in_use = host_bridges.list_iface()
            target_ifaces = list(ifaces_in_use + br_in_use)
        if (
            process.system(
                "which ovs-vsctl && systemctl status openvswitch.service",
                ignore_status=True,
                shell=True,
            )
            == 0
        ):
            ovs_br_all = netperf_base.ssh_cmd(host, "ovs-vsctl list-br")
            ovs_br = []
            if ovs_br_all:
                for nic in vm.virtnet:
                    if nic.netdst in ovs_br_all:
                        ovs_br.append(nic.netdst)
                    elif nic.nettype == "vdpa":
                        vf_pci = netperf_base.ssh_cmd(
                            host,
                            "vdpa dev show |grep %s | grep -o 'pci/[^[:space:]]*' | "
                            "awk -F/ '{print $2}'" % nic.netdst,
                        )
                        pf_pci = netperf_base.ssh_cmd(
                            host,
                            "grep PCI_SLOT_NAME /sys/bus/pci/devices/%s/physfn/uevent |"
                            " cut -d'=' -f2" % vf_pci,
                        )
                        port = netperf_base.ssh_cmd(
                            host, "ls /sys/bus/pci/devices/%s/net/ | head -n 1" % pf_pci
                        )
                        ovs_br_vdpa = netperf_base.ssh_cmd(
                            host, "ovs-vsctl port-to-br %s" % port
                        )
                        cmd = (
                            f"ovs-ofctl add-flow {ovs_br_vdpa} '"
                            "in_port=1,idle_timeout=0 actions=output:2'"
                        )
                        cmd += (
                            f"&&  ovs-ofctl add-flow {ovs_br_vdpa} '"
                            "in_port=2,idle_timeout=0 actions=output:1'"
                        )
                        cmd += "&&  ovs-ofctl dump-flows {}".format(ovs_br_vdpa)
                        netperf_base.ssh_cmd(host, cmd)
                        ovs_br.append(ovs_br_vdpa)
                for br in ovs_br:
                    ovs_list = "ovs-vsctl list-ports %s" % br
                    ovs_port = netperf_base.ssh_cmd(host, ovs_list)
                    target_ifaces.extend(ovs_port.split() + [br])
        if vm.virtnet[0].nettype == "macvtap":
            target_ifaces.extend([vm.virtnet[0].netdst, vm.get_ifname(0)])
        error_context.context("Change all Bridge NICs MTU to %s" % mtu, test.log.info)
        for iface in target_ifaces:
            try:
                process.run(
                    host_mtu_cmd % (iface, mtu), ignore_status=False, shell=True
                )
            except process.CmdError as err:
                if "SIOCSIFMTU" in err.result.stderr.decode():
                    test.cancel(
                        "The ethenet device does not support jumbo," "cancel test"
                    )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    config_cmds = params.get("config_cmds")
    if config_cmds:
        for config_cmd in config_cmds.split(","):
            cmd = params.get(config_cmd.strip())
            session = vm.wait_for_serial_login(timeout=login_timeout)
            if cmd:
                s, o = session.cmd_status_output(cmd)
                test.log.info(o)
                if "querysettings" in cmd:
                    if ".sys" in o:
                        verifier_clear_cmd = "verifier /reset"
                        status, output = session.cmd_status_output(verifier_clear_cmd)
                        test.log.info(output)
                        if ".sys" in output:
                            msg = "%s does not work correctly" % verifier_clear_cmd
                            test.error(msg)
                elif s != 0:
                    msg = "Config command %s failed. Output: %s" % (cmd, o)
                    test.error(msg)
            session.close()
        if params.get("reboot_after_config", "yes") == "yes":
            vm.reboot(method="system_reset", serial=True)

    failover_exist = False
    for i in params.get("nics").split():
        nic_params = params.object_params(i)
        if nic_params.get("failover_pair_id"):
            failover_exist = True
            break
    if failover_exist:
        if params.get("os_type") == "linux":
            session = vm.wait_for_serial_login(timeout=login_timeout)
            ifname = utils_net.get_linux_ifname(session)
            for i in ifname:
                cmd = "ethtool -i %s |grep driver| awk -F': ' '{print $2}'" % i
                driver = session.cmd_output(cmd).strip()
                if driver == "net_failover":
                    session.cmd_output("dhclient -r && dhclient %s" % i)
                    break
        if params.get("os_type") == "windows" and params.get("install_vioprot_cmd"):
            media_type = params["virtio_win_media_type"]
            driver_name = params["driver_name"]
            session = vm.wait_for_login(nic_index=2, timeout=login_timeout)
            for driver_name in driver_name.split():
                inf_path = win_driver_utils.get_driver_inf_path(
                    session, test, media_type, driver_name
                )
                if driver_name == "netkvm":
                    device_name = params.get("device_name")
                    device_hwid = params.get("device_hwid")
                    devcon_path = utils_misc.set_winutils_letter(
                        session, params.get("devcon_path")
                    )
                    status, output = session.cmd_status_output("dir %s" % devcon_path)
                    if status:
                        test.error("Not found devcon.exe, details: %s" % output)

                    error_context.context(
                        "Uninstall %s driver" % driver_name, test.log.info
                    )
                    win_driver_utils.uninstall_driver(
                        session,
                        test,
                        devcon_path,
                        driver_name,
                        device_name,
                        device_hwid,
                    )
                    for hwid in device_hwid.split():
                        install_driver_cmd = "%s install %s %s" % (
                            devcon_path,
                            inf_path,
                            hwid,
                        )
                        status, output = session.cmd_status_output(
                            install_driver_cmd, timeout=login_timeout
                        )
                        if status:
                            test.fail(
                                "Failed to install driver '%s', "
                                "details:\n%s" % (driver_name, output)
                            )
                if driver_name == "VIOPROT":
                    test.log.info("Will install inf file found at '%s'", inf_path)
                    install_cmd = params.get("install_vioprot_cmd") % inf_path
                    status, output = session.cmd_status_output(install_cmd)
                    if status:
                        test.error("Install inf file failed, output=%s" % output)
                session.cmd_output_safe("ipconfig /renew", timeout=login_timeout)
            session.close()
    else:
        try:
            vm.wait_for_serial_login(
                timeout=login_timeout, restart_network=True
            ).close()
        except virt_vm.VMIPAddressMissingError:
            pass

    if len(params.get("nics", "").split()) > 1:
        session = vm.wait_for_login(nic_index=1, timeout=login_timeout)
    else:
        session = vm.wait_for_login(timeout=login_timeout)

    mac = vm.get_mac_address(0)
    if params.get("os_type") == "linux":
        ethname = utils_net.get_linux_ifname(session, mac)
    queues = int(params.get("queues", 1))
    if queues > 1:
        if params.get("os_type") == "linux":
            session.cmd_status_output("ethtool -L %s combined %s" % (ethname, queues))
        else:
            test.log.info("FIXME: support to enable MQ for Windows guest!")

    if params.get("server_private_ip") and params.get("os_type") == "linux":
        server_ip = params.get("server_private_ip")
        cmd = "systemctl stop NetworkManager.service"
        cmd += " && ifconfig %s %s up" % (ethname, server_ip)
        session.cmd_output(cmd)
    else:
        server_ip = vm.wait_for_get_address(0, timeout=90)

    if len(params.get("nics", "").split()) > 1:
        server_ctl = vm.wait_for_login(nic_index=1, timeout=login_timeout)
        server_ctl_ip = vm.wait_for_get_address(1, timeout=90)
    else:
        server_ctl = vm.wait_for_login(timeout=login_timeout)
        server_ctl_ip = server_ip

    if params.get("rh_perf_envsetup_script"):
        utils_test.service_setup(vm, session, test.virtdir)
    session.close()

    if params.get("os_type") == "windows" and params.get("use_cygwin") == "yes":
        cygwin_prompt = params.get("cygwin_prompt", r"\$\s+$")
        cygwin_start = params.get("cygwin_start")
        server_cyg = vm.wait_for_login(timeout=login_timeout)
        server_cyg.set_prompt(cygwin_prompt)
        server_cyg.cmd_output(cygwin_start)
    else:
        server_cyg = None

    test.log.debug(
        process.system_output(
            "numactl --hardware", verbose=False, ignore_status=True, shell=True
        ).decode()
    )
    test.log.debug(
        process.system_output(
            "numactl --show", verbose=False, ignore_status=True, shell=True
        ).decode()
    )
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    numa_node = netperf_base.pin_vm_threads(vm, params.get("numa_node"))

    host = params.get("host", "localhost")
    host_ip = host
    if host != "localhost":
        params_host = params.object_params("host")
        host = remote.wait_for_login(
            params_host.get("shell_client"),
            host_ip,
            params_host.get("shell_port"),
            params_host.get("username"),
            params_host.get("password"),
            params_host.get("shell_prompt"),
        )

    client = params.get("client", "localhost")
    client_ip = client
    clients = []
    # client session 1 for control, session 2 for data communication
    for i in range(2):
        if client in params.get("vms"):
            vm_client = env.get_vm(client)
            tmp = vm_client.wait_for_login(timeout=login_timeout)
            client_ip = vm_client.wait_for_get_address(0, timeout=5)
        elif client != "localhost" and params.get("os_type_client") == "linux":
            client_pub_ip = params.get("client_public_ip")
            tmp = remote.wait_for_login(
                params.get("shell_client_client"),
                client_pub_ip,
                params.get("shell_port_client"),
                params.get("username_client"),
                params.get("password_client"),
                params.get("shell_prompt_client"),
            )
            cmd = "ifconfig %s %s up" % (params.get("client_physical_nic"), client_ip)
            netperf_base.ssh_cmd(tmp, cmd)
        else:
            tmp = "localhost"
        clients.append(tmp)
    client = clients[0]

    vms_list = params["vms"].split()
    if len(vms_list) > 1:
        vm2 = env.get_vm(vms_list[-1])
        vm2.verify_alive()
        session2 = vm2.wait_for_login(timeout=login_timeout)
        if params.get("rh_perf_envsetup_script"):
            utils_test.service_setup(vm2, session2, test.virtdir)
        client = vm2.wait_for_login(timeout=login_timeout)
        client_ip = vm2.get_address()
        session2.close()
        netperf_base.pin_vm_threads(vm2, numa_node)

    error_context.context("Prepare env of server/client/host", test.log.info)
    prepare_list = set([server_ctl, client, host])
    tag_dict = {server_ctl: "server", client: "client", host: "host"}
    if client_pub_ip:
        ip_dict = {server_ctl: server_ctl_ip, client: client_pub_ip, host: host_ip}
    else:
        ip_dict = {server_ctl: server_ctl_ip, client: client_ip, host: host_ip}
    for i in prepare_list:
        params_tmp = params.object_params(tag_dict[i])
        if params_tmp.get("os_type") == "linux":
            shell_port = int(params_tmp["shell_port"])
            password = params_tmp["password"]
            username = params_tmp["username"]
            netperf_base.env_setup(
                test, params, i, ip_dict[i], username, shell_port, password
            )
        elif params_tmp.get("os_type") == "windows":
            windows_disable_firewall = params.get("windows_disable_firewall")
            netperf_base.ssh_cmd(i, windows_disable_firewall)
    netperf_base.tweak_tuned_profile(params, server_ctl, client, host)
    mtu = int(params.get("mtu", "1500"))
    mtu_set(mtu)

    env.stop_ip_sniffing()

    try:
        error_context.context("Start netperf testing", test.log.info)
        start_test(
            server_ip,
            server_ctl,
            host,
            clients,
            test.resultsdir,
            test_duration=int(params.get("l")),
            sessions_rr=params.get("sessions_rr"),
            sessions=params.get("sessions"),
            sizes_rr=params.get("sizes_rr"),
            sizes=params.get("sizes"),
            protocols=params.get("protocols"),
            netserver_port=params.get("netserver_port", "12865"),
            params=params,
            server_cyg=server_cyg,
            test=test,
        )

        if params.get("log_hostinfo_script"):
            src = os.path.join(test.virtdir, params.get("log_hostinfo_script"))
            path = os.path.join(test.resultsdir, "systeminfo")
            process.system_output(
                "bash %s %s &> %s" % (src, test.resultsdir, path), shell=True
            )

        if params.get("log_guestinfo_script") and params.get("log_guestinfo_exec"):
            src = os.path.join(test.virtdir, params.get("log_guestinfo_script"))
            path = os.path.join(test.resultsdir, "systeminfo")
            destpath = params.get("log_guestinfo_path", "/tmp/log_guestinfo.sh")
            vm.copy_files_to(src, destpath, nic_index=1)
            logexec = params.get("log_guestinfo_exec", "bash")
            output = server_ctl.cmd_output("%s %s" % (logexec, destpath))
            logfile = open(path, "a+")
            logfile.write(output)
            logfile.close()
    finally:
        if mtu != 1500:
            mtu_default = 1500
            error_context.context(
                "Change back server, client and host's mtu to %s" % mtu_default
            )
            mtu_set(mtu_default)
        if (
            params.get("client_physical_nic")
            and params.get("os_type_client") == "linux"
        ):
            cmd = "ifconfig %s 0.0.0.0" % params.get("client_physical_nic")
            netperf_base.ssh_cmd(client, cmd)


# FIXME: `test` should be a mandatory argument here
@error_context.context_aware
def start_test(
    server,
    server_ctl,
    host,
    clients,
    resultsdir,
    test_duration=60,
    sessions_rr="50 100 250 500",
    sessions="1 2 4",
    sizes_rr="64 256 512 1024 2048",
    sizes="64 256 512 1024 2048 4096",
    protocols="TCP_STREAM TCP_MAERTS TCP_RR TCP_CRR",
    netserver_port=None,
    params=None,
    server_cyg=None,
    test=None,
):
    """
    Start to test with different kind of configurations

    :param server: netperf server ip for data connection
    :param server_ctl: ip to control netperf server
    :param host: localhost ip
    :param clients: netperf clients' ip
    :param resultsdir: directory to restore the results
    :param test_duration: test duration
    :param sessions_rr: sessions number list for RR test
    :param sessions: sessions number list
    :param sizes_rr: request/response sizes (TCP_RR, UDP_RR)
    :param sizes: send size (TCP_STREAM, UDP_STREAM)
    :param protocols: test type
    :param netserver_port: netserver listen port
    :param params: Dictionary with the test parameters.
    :param server_cyg: shell session for cygwin in windows guest
    """
    if params is None:
        params = {}

    fd = open("%s/netperf-result.%s.RHS" % (resultsdir, time.time()), "w")
    netperf_base.record_env_version(test, params, host, server_ctl, fd, test_duration)

    record_list = [
        "size",
        "sessions",
        "throughput",
        "trans.rate",
        "CPU",
        "thr_per_CPU",
        "rx_pkts",
        "tx_pkts",
        "rx_byts",
        "tx_byts",
        "re_pkts",
        "exits",
        "tpkt_per_exit",
    ]

    for i in range(int(params.get("queues", 0))):
        record_list.append("rx_intr_%s" % i)
    record_list.append("rx_intr_sum")
    for i in range(int(params.get("queues", 0))):
        record_list.append("tx_intr_%s" % i)
    record_list.append("tx_intr_sum")
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    output = netperf_base.ssh_cmd(host, "mpstat 1 1 |grep CPU")
    mpstat_head = re.findall(r"CPU\s+.*", output)[0].split()
    mpstat_key = params.get("mpstat_key", "%idle")
    if mpstat_key in mpstat_head:
        mpstat_index = mpstat_head.index(mpstat_key) + 1
    else:
        mpstat_index = 0

    for protocol in protocols.split():
        error_context.context("Testing %s protocol" % protocol, test.log.info)
        protocol_log = ""
        if protocol in ("TCP_RR", "TCP_CRR"):
            sessions_test = sessions_rr.split()
            sizes_test = sizes_rr.split()
            protocol_log = protocol
        else:
            sessions_test = sessions.split()
            sizes_test = sizes.split()
            if protocol == "TCP_STREAM":
                protocol_log = protocol + " (RX)"
            elif protocol == "TCP_MAERTS":
                protocol_log = protocol + " (TX)"
        fd.write("Category:" + protocol_log + "\n")

        record_header = True
        for i in sizes_test:
            for j in sessions_test:
                if protocol in ("TCP_RR", "TCP_CRR"):
                    nf_args = "-t %s -v 1 -- -r %s,%s" % (protocol, i, i)
                elif protocol == "TCP_MAERTS":
                    nf_args = "-C -c -t %s -- -m ,%s" % (protocol, i)
                else:
                    nf_args = "-C -c -t %s -- -m %s" % (protocol, i)

                ret = launch_client(
                    j,
                    server,
                    server_ctl,
                    host,
                    clients,
                    test_duration,
                    nf_args,
                    netserver_port,
                    params,
                    server_cyg,
                    test,
                )
                if ret:
                    thu = float(ret["thu"])
                    cpu = 100 - float(ret["mpstat"].split()[mpstat_index])
                    normal = thu / cpu
                    if ret.get("tx_pkt") and ret.get("exits"):
                        ret["tpkt_per_exit"] = float(ret["tx_pkts"]) / float(
                            ret["exits"]
                        )

                    ret["size"] = int(i)
                    ret["sessions"] = int(j)
                    if protocol in ("TCP_RR", "TCP_CRR"):
                        ret["trans.rate"] = thu
                    else:
                        ret["throughput"] = thu
                    ret["CPU"] = cpu
                    ret["thr_per_CPU"] = normal
                    row, key_list = netperf_base.netperf_record(
                        ret, record_list, header=record_header, base=base, fbase=fbase
                    )
                    category = ""
                    if record_header:
                        record_header = False
                        category = row.split("\n")[0]

                    test.write_test_keyval({"category": category})
                    prefix = "%s--%s--%s" % (protocol, i, j)
                    for key in key_list:
                        test.write_test_keyval({"%s--%s" % (prefix, key): ret[key]})

                    test.log.info(row)
                    fd.write(row + "\n")

                    fd.flush()

                    test.log.debug("Remove temporary files")
                    process.system_output(
                        "rm -f /tmp/netperf.%s.nf" % ret["pid"],
                        verbose=False,
                        ignore_status=True,
                        shell=True,
                    )
                    test.log.info("Netperf thread completed successfully")
                else:
                    test.log.debug(
                        "Not all netperf clients start to work, please enlarge"
                        " '%s' number or skip this tests",
                        int(j),
                    )
                    continue
    fd.close()


@error_context.context_aware
def launch_client(
    sessions,
    server,
    server_ctl,
    host,
    clients,
    l,
    nf_args,
    port,
    params,
    server_cyg,
    test,
):
    """Launch netperf clients"""

    netperf_version = params.get("netperf_version", "2.6.0")
    client_path = "/tmp/netperf-%s/src/netperf" % netperf_version
    server_path = "/tmp/netperf-%s/src/netserver" % netperf_version
    get_status_flag = params.get("get_status_in_guest", "no") == "yes"
    global _netserver_started
    # Start netserver
    if _netserver_started:
        test.log.debug("Netserver already started.")
    else:
        error_context.context("Start Netserver on guest", test.log.info)
        if params.get("os_type") == "windows":
            timeout = float(params.get("timeout", "240"))
            cdrom_drv = utils_misc.get_winutils_vol(server_ctl)
            if params.get("use_cygwin") == "yes":
                netserv_start_cmd = params.get("netserv_start_cmd")
                netperf_src = params.get("netperf_src") % cdrom_drv
                cygwin_root = params.get("cygwin_root")
                netserver_path = params.get("netserver_path")
                netperf_install_cmd = params.get("netperf_install_cmd")
                start_session = server_cyg
                test.log.info(
                    "Start netserver with cygwin, cmd is: %s", netserv_start_cmd
                )
                if "netserver" not in server_ctl.cmd_output("tasklist"):
                    netperf_pack = "netperf-%s" % params.get("netperf_version")
                    s_check_cmd = "dir %s" % netserver_path
                    p_check_cmd = "dir %s" % cygwin_root
                    if not (
                        "netserver.exe" in server_ctl.cmd(s_check_cmd)
                        and netperf_pack in server_ctl.cmd(p_check_cmd)
                    ):
                        error_context.context(
                            "Install netserver in Windows guest cygwin", test.log.info
                        )
                        cmd = "xcopy %s %s /S /I /Y" % (netperf_src, cygwin_root)
                        server_ctl.cmd(cmd)
                        server_cyg.cmd_output(netperf_install_cmd, timeout=timeout)
                        if "netserver.exe" not in server_ctl.cmd(s_check_cmd):
                            err_msg = "Install netserver cygwin failed"
                            test.error(err_msg)
                        test.log.info("Install netserver in cygwin successfully")
            else:
                start_session = server_ctl
                netserv_start_cmd = params.get("netserv_start_cmd") % cdrom_drv
                test.log.info(
                    "Start netserver without cygwin, cmd is: %s", netserv_start_cmd
                )

            error_context.context("Start netserver on windows guest", test.log.info)
            start_netserver_win(start_session, netserv_start_cmd, test)

        else:
            test.log.info("Netserver start cmd is '%s'", server_path)
            netperf_base.ssh_cmd(server_ctl, "pidof netserver || %s" % server_path)
            ncpu = netperf_base.ssh_cmd(
                server_ctl, "cat /proc/cpuinfo |grep processor |wc -l"
            )
            ncpu = re.findall(r"\d+", ncpu)[-1]

        test.log.info("Netserver start successfully")

    def count_interrupt(name):
        """
        Get a list of interrut number for each queue

        @param name: the name of interrupt, such as "virtio0-input"
        """
        sum = 0
        intr = []
        stat = netperf_base.ssh_cmd(server_ctl, "grep %s /proc/interrupts" % name)
        for i in stat.strip().split("\n"):
            for cpu in range(int(ncpu)):
                sum += int(i.split()[cpu + 1])
            intr.append(sum)
            sum = 0
        return intr

    def get_state():
        ifname = None
        for i in netperf_base.ssh_cmd(server_ctl, "ifconfig").split("\n\n"):
            if server in i:
                ifname = re.findall(r"(\w+\d+)[:\s]", i)[0]
        if ifname is None:
            raise RuntimeError(f"no available iface associated with {server}")

        path = "find /sys/devices|grep net/%s/statistics" % ifname
        cmd = (
            "%s/rx_packets|xargs cat;%s/tx_packets|xargs cat;"
            "%s/rx_bytes|xargs cat;%s/tx_bytes|xargs cat" % (path, path, path, path)
        )
        output = netperf_base.ssh_cmd(server_ctl, cmd).split()[-4:]

        nrx = int(output[0])
        ntx = int(output[1])
        nrxb = int(output[2])
        ntxb = int(output[3])

        nre = int(
            netperf_base.ssh_cmd(server_ctl, "grep Tcp /proc/net/snmp|tail -1").split()[
                12
            ]
        )
        state_list = [
            "rx_pkts",
            nrx,
            "tx_pkts",
            ntx,
            "rx_byts",
            nrxb,
            "tx_byts",
            ntxb,
            "re_pkts",
            nre,
        ]
        try:
            nrx_intr = count_interrupt("virtio.-input")
            ntx_intr = count_interrupt("virtio.-output")
            sum = 0
            for i in range(len(nrx_intr)):
                state_list.append("rx_intr_%s" % i)
                state_list.append(nrx_intr[i])
                sum += nrx_intr[i]
            state_list.append("rx_intr_sum")
            state_list.append(sum)

            sum = 0
            for i in range(len(ntx_intr)):
                state_list.append("tx_intr_%s" % i)
                state_list.append(ntx_intr[i])
                sum += ntx_intr[i]
            state_list.append("tx_intr_sum")
            state_list.append(sum)

        except IndexError:
            ninit = count_interrupt("virtio.")
            state_list.append("intr")
            state_list.append(ninit)

        exits = int(netperf_base.ssh_cmd(host, "cat /sys/kernel/debug/kvm/exits"))
        state_list.append("exits")
        state_list.append(exits)

        return state_list

    def thread_cmd(params, i, numa_enable, client_s, timeout):
        fname = "/tmp/netperf.%s.nf" % pid
        option = "`command -v python python3 | head -1 ` "
        option += "/tmp/netperf_agent.py %d %s -D 1 -H %s -l %s %s" % (
            i,
            client_path,
            server,
            int(l) * 1.5,
            nf_args,
        )
        option += " >> %s" % fname
        netperf_base.netperf_thread(params, numa_enable, client_s, option, fname)

    def all_clients_up():
        try:
            content = netperf_base.ssh_cmd(clients[-1], "cat %s" % fname)
        except:
            content = ""
            return False
        if int(sessions) == len(re.findall("MIGRATE", content)):
            return True
        return False

    def stop_netperf_clients():
        if params.get("os_type_client") == "linux":
            netperf_base.ssh_cmd(
                clients[-1], params.get("client_kill_linux"), ignore_status=True
            )
        else:
            netperf_base.ssh_cmd(
                clients[-1], params.get("client_kill_windows"), ignore_status=True
            )

    def parse_demo_result(fname, sessions):
        """
        Process the demo result, remove the noise from head,
        and compute the final throughout.

        :param fname: result file name
        :param sessions: sessions' number
        """
        fd = open(fname)
        lines = fd.readlines()
        fd.close()

        for i in range(1, len(lines) + 1):
            if "AF_INET" in lines[-i]:
                break
        nresult = i - 1
        if nresult < int(sessions):
            test.error(
                "We couldn't expect this parallism, expect %s get %s"
                % (sessions, nresult)
            )

        niteration = nresult // sessions
        result = 0.0
        for this in lines[-sessions * niteration :]:
            if "Interim" in this:
                result += float(re.findall(r"Interim result: *(\S+)", this)[0])
        result = result / niteration
        test.log.debug("niteration: %s", niteration)
        return result

    tries = int(params.get("tries", 1))
    while tries > 0:
        error_context.context("Start netperf client threads", test.log.info)
        pid = str(os.getpid())
        fname = "/tmp/netperf.%s.nf" % pid
        netperf_base.ssh_cmd(clients[-1], "rm -f %s" % fname)
        numa_enable = params.get("netperf_with_numa", "yes") == "yes"
        timeout_netperf_start = int(l) * 0.5
        client_thread = threading.Thread(
            target=thread_cmd,
            kwargs={
                "params": params,
                "i": int(sessions),
                "numa_enable": numa_enable,
                "client_s": clients[0],
                "timeout": timeout_netperf_start,
            },
        )
        client_thread.start()

        ret = {}
        ret["pid"] = pid

        if utils_misc.wait_for(
            all_clients_up,
            timeout_netperf_start,
            0.0,
            0.2,
            "Wait until all netperf clients start to work",
        ):
            test.log.debug("All netperf clients start to work.")

            # real & effective test starts
            if get_status_flag:
                start_state = get_state()
            ret["mpstat"] = netperf_base.ssh_cmd(
                host, "mpstat 1 %d |tail -n 1" % (l - 1)
            )
            finished_result = netperf_base.ssh_cmd(clients[-1], "cat %s" % fname)

            # stop netperf clients
            stop_netperf_clients()

            # real & effective test ends
            if get_status_flag:
                end_state = get_state()
                if len(start_state) != len(end_state):
                    msg = "Initial state not match end state:\n"
                    msg += "  start state: %s\n" % start_state
                    msg += "  end state: %s\n" % end_state
                    test.log.warning(msg)
                else:
                    for i in range(len(end_state) // 2):
                        ret[end_state[i * 2]] = (
                            end_state[i * 2 + 1] - start_state[i * 2 + 1]
                        )

            client_thread.join()

            error_context.context("Testing Results Treatment and Report", test.log.info)
            f = open(fname, "w")
            f.write(finished_result)
            f.close()
            ret["thu"] = parse_demo_result(fname, int(sessions))
            return ret
            break
        else:
            stop_netperf_clients()
            tries = tries - 1
            test.log.debug("left %s times", tries)
