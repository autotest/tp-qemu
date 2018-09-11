import logging
import os
import threading
import re
import six
import time

from avocado.utils import process

from virttest import utils_test
from virttest import utils_misc
from virttest import utils_net
from virttest import remote
from virttest import data_dir
from virttest import error_context

_netserver_started = False


def format_result(result, base="12", fbase="5"):
    """
    Format the result to a fixed length string.

    :param result: result need to convert
    :param base: the length of converted string
    :param fbase: the decimal digit for float
    """
    if isinstance(result, six.string_types):
        value = "%" + base + "s"
    elif isinstance(result, int):
        value = "%" + base + "d"
    elif isinstance(result, float):
        value = "%" + base + "." + fbase + "f"
    return value % result


def netperf_record(results, filter_list, header=False, base="12", fbase="2"):
    """
    Record the results in a certain format.

    :param results: a dict include the results for the variables
    :param filter_list: variable list which is wanted to be shown in the
                        record file, also fix the order of variables
    :param header: if record the variables as a column name before the results
    :param base: the length of a variable
    :param fbase: the decimal digit for float
    """
    key_list = []
    for key in filter_list:
        if key in results:
            key_list.append(key)

    record = ""
    if header:
        for key in key_list:
            record += "%s|" % format_result(key, base=base, fbase=fbase)
        record = record.rstrip("|")
        record += "\n"
    for key in key_list:
        record += "%s|" % format_result(results[key], base=base, fbase=fbase)
    record = record.rstrip("|")
    return record, key_list


def start_netserver_win(session, start_cmd, test):
    check_reg = re.compile(r"NETSERVER.*EXE", re.I)
    if not check_reg.findall(session.cmd_output("tasklist")):
        session.sendline(start_cmd)
        if not utils_misc.wait_for(lambda: check_reg.findall(
                                   session.cmd_output("tasklist")),
                                   30, 5, 1, "Wait netserver start"):
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
    def env_setup(session, ip, user, port, password):
        error_context.context("Setup env for %s" % ip)
        if params.get("env_setup_cmd"):
            ssh_cmd(session, params.get("env_setup_cmd"), ignore_status=True)

        pkg = params["netperf_pkg"]
        pkg = os.path.join(data_dir.get_deps_dir(), pkg)
        remote.scp_to_remote(ip, shell_port, username, password, pkg, "/tmp")
        ssh_cmd(session, params.get("setup_cmd"))

        agent_path = os.path.join(test.virtdir, "scripts/netperf_agent.py")
        remote.scp_to_remote(ip, shell_port, username, password,
                             agent_path, "/tmp")

    def mtu_set(mtu):
        """
        Set server/client/host's mtu

        :param mtu: mtu value to be set
        """

        server_mtu_cmd = params.get("server_mtu_cmd")
        client_mtu_cmd = params.get("client_mtu_cmd")
        host_mtu_cmd = params.get("host_mtu_cmd")
        error_context.context("Changing the MTU of guest", logging.info)
        if params.get("os_type") == "linux":
            ethname = utils_net.get_linux_ifname(server_ctl, mac)
            ssh_cmd(server_ctl, server_mtu_cmd % (ethname, mtu))
        elif params.get("os_type") == "windows":
            connection_id = utils_net.get_windows_nic_attribute(
                server_ctl, "macaddress", mac, "netconnectionid")
            ssh_cmd(server_ctl, server_mtu_cmd % (connection_id, mtu))

        error_context.context("Changing the MTU of client", logging.info)
        ssh_cmd(client, client_mtu_cmd
                % (params.get("client_physical_nic"), mtu))

        netdst = params.get("netdst", "switch")
        host_bridges = utils_net.Bridge()
        br_in_use = host_bridges.list_br()
        if netdst in br_in_use:
            ifaces_in_use = host_bridges.list_iface()
            target_ifaces = list(ifaces_in_use + br_in_use)
        if vm.virtnet[0].nettype == "macvtap":
            target_ifaces.extend([vm.virtnet[0].netdst, vm.get_ifname(0)])
        error_context.context("Change all Bridge NICs MTU to %s"
                              % mtu, logging.info)
        for iface in target_ifaces:
            try:
                process.run(host_mtu_cmd % (iface, mtu), ignore_status=False,
                            shell=True)
            except process.CmdError as err:
                if "SIOCSIFMTU" in err.result.stderr.decode():
                    test.cancel("The ethenet device does not support jumbo,"
                                "cancel test")

    def tweak_tuned_profile():
        """

        Tweak configuration with truned profile

        """

        client_tuned_profile = params.get("client_tuned_profile")
        server_tuned_profile = params.get("server_tuned_profile")
        host_tuned_profile = params.get("host_tuned_profile")
        error_context.context("Changing tune profile of guest", logging.info)
        if params.get("os_type") == "linux" and server_tuned_profile:
            ssh_cmd(server_ctl, server_tuned_profile)

        error_context.context("Changing tune profile of client/host",
                              logging.info)
        if client_tuned_profile:
            ssh_cmd(client, client_tuned_profile)
        if host_tuned_profile:
            ssh_cmd(host, host_tuned_profile)

    def _pin_vm_threads(vm, node):
        if node:
            if not isinstance(node, utils_misc.NumaNode):
                node = utils_misc.NumaNode(int(node))
            utils_test.qemu.pin_vm_threads(vm, node)

        return node

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))

    vm.wait_for_serial_login(timeout=login_timeout, restart_network=True).close()
    if len(params.get("nics", "").split()) > 1:
        session = vm.wait_for_login(nic_index=1, timeout=login_timeout)
    else:
        session = vm.wait_for_login(timeout=login_timeout)

    config_cmds = params.get("config_cmds")
    if config_cmds:
        for config_cmd in config_cmds.split(","):
            cmd = params.get(config_cmd.strip())
            if cmd:
                s, o = session.cmd_status_output(cmd)
                if s:
                    msg = "Config command %s failed. Output: %s" % (cmd, o)
                    test.error(msg)
        if params.get("reboot_after_config", "yes") == "yes":
            session = vm.reboot(session=session, timeout=login_timeout)
            vm.wait_for_serial_login(timeout=login_timeout, restart_network=True).close()

    server_ip = vm.wait_for_get_address(0, timeout=90)
    if len(params.get("nics", "").split()) > 1:
        server_ctl = vm.wait_for_login(nic_index=1, timeout=login_timeout)
        server_ctl_ip = vm.wait_for_get_address(1, timeout=90)
    else:
        server_ctl = vm.wait_for_login(timeout=login_timeout)
        server_ctl_ip = server_ip

    mac = vm.get_mac_address(0)
    queues = int(params.get("queues", 1))
    if queues > 1:
        if params.get("os_type") == "linux":
            ethname = utils_net.get_linux_ifname(session, mac)
            session.cmd_status_output("ethtool -L %s combined %s" %
                                      (ethname, queues))
        else:
            logging.info("FIXME: support to enable MQ for Windows guest!")

    if params.get("rh_perf_envsetup_script"):
        utils_test.service_setup(vm, session, test.virtdir)
    session.close()

    if (params.get("os_type") == "windows" and
            params.get("use_cygwin") == "yes"):
        cygwin_prompt = params.get("cygwin_prompt", r"\$\s+$")
        cygwin_start = params.get("cygwin_start")
        server_cyg = vm.wait_for_login(timeout=login_timeout)
        server_cyg.set_prompt(cygwin_prompt)
        server_cyg.cmd_output(cygwin_start)
    else:
        server_cyg = None

    logging.debug(process.system_output("numactl --hardware",
                                        verbose=False, ignore_status=True,
                                        shell=True).decode())
    logging.debug(process.system_output("numactl --show",
                                        verbose=False, ignore_status=True,
                                        shell=True).decode())
    # pin guest vcpus/memory/vhost threads to last numa node of host by default
    numa_node = _pin_vm_threads(vm, params.get("numa_node"))

    host = params.get("host", "localhost")
    host_ip = host
    if host != "localhost":
        params_host = params.object_params("host")
        host = remote.wait_for_login(params_host.get("shell_client"),
                                     host_ip,
                                     params_host.get("shell_port"),
                                     params_host.get("username"),
                                     params_host.get("password"),
                                     params_host.get("shell_prompt"))

    client = params.get("client", "localhost")
    client_ip = client
    clients = []
    # client session 1 for control, session 2 for data communication
    for i in range(2):
        if client in params.get("vms"):
            vm_client = env.get_vm(client)
            tmp = vm_client.wait_for_login(timeout=login_timeout)
            client_ip = vm_client.wait_for_get_address(0, timeout=5)
        elif client != "localhost":
            tmp = remote.wait_for_login(params.get("shell_client_client"),
                                        client_ip,
                                        params.get("shell_port_client"),
                                        params.get("username_client"),
                                        params.get("password_client"),
                                        params.get("shell_prompt_client"))
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
        _pin_vm_threads(vm2, numa_node)

    error_context.context("Prepare env of server/client/host", logging.info)
    prepare_list = set([server_ctl, client, host])
    tag_dict = {server_ctl: "server", client: "client", host: "host"}
    ip_dict = {server_ctl: server_ctl_ip, client: client_ip, host: host_ip}
    for i in prepare_list:
        params_tmp = params.object_params(tag_dict[i])
        if params_tmp.get("os_type") == "linux":
            shell_port = int(params_tmp["shell_port"])
            password = params_tmp["password"]
            username = params_tmp["username"]
            env_setup(i, ip_dict[i], username, shell_port, password)
    tweak_tuned_profile()
    mtu = int(params.get("mtu", "1500"))
    mtu_set(mtu)

    env.stop_ip_sniffing()

    try:
        error_context.context("Start netperf testing", logging.info)
        start_test(server_ip, server_ctl, host, clients, test.resultsdir,
                   test_duration=int(params.get('l')),
                   sessions_rr=params.get('sessions_rr'),
                   sessions=params.get('sessions'),
                   sizes_rr=params.get('sizes_rr'),
                   sizes=params.get('sizes'),
                   protocols=params.get('protocols'),
                   ver_cmd=params.get('ver_cmd', "rpm -q qemu-kvm"),
                   netserver_port=params.get('netserver_port', "12865"),
                   params=params, server_cyg=server_cyg, test=test)

        if params.get("log_hostinfo_script"):
            src = os.path.join(test.virtdir, params.get("log_hostinfo_script"))
            path = os.path.join(test.resultsdir, "systeminfo")
            process.system_output("bash %s %s &> %s" % (
                                  src, test.resultsdir, path), shell=True)

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
            error_context.context("Change back server, client and host's mtu to %s"
                                  % mtu_default)
            mtu_set(mtu_default)


@error_context.context_aware
def start_test(server, server_ctl, host, clients, resultsdir, test_duration=60,
               sessions_rr="50 100 250 500",
               sessions="1 2 4",
               sizes_rr="64 256 512 1024 2048",
               sizes="64 256 512 1024 2048 4096",
               protocols="TCP_STREAM TCP_MAERTS TCP_RR TCP_CRR", ver_cmd=None,
               netserver_port=None, params=None, server_cyg=None, test=None):
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
    :param ver_cmd: command to check kvm version
    :param netserver_port: netserver listen port
    :param params: Dictionary with the test parameters.
    :param server_cyg: shell session for cygwin in windows guest
    """
    if params is None:
        params = {}

    guest_ver_cmd = params.get("guest_ver_cmd", "uname -r")
    fd = open("%s/netperf-result.%s.RHS" % (resultsdir, time.time()), "w")

    test.write_test_keyval({'kvm-userspace-ver': ssh_cmd(host,
                            ver_cmd).strip()})
    test.write_test_keyval({'guest-kernel-ver': ssh_cmd(server_ctl,
                            guest_ver_cmd).strip()})
    test.write_test_keyval({'session-length': test_duration})

    fd.write('### kvm-userspace-ver : %s\n' % ssh_cmd(host,
                                                      ver_cmd).strip())
    fd.write('### guest-kernel-ver : %s\n' % ssh_cmd(server_ctl,
                                                     guest_ver_cmd).strip())
    fd.write('### kvm_version : %s\n' % os.uname()[2])
    fd.write('### session-length : %s\n' % test_duration)

    record_list = ['size', 'sessions', 'throughput', 'trans.rate', 'CPU',
                   'thr_per_CPU', 'rx_pkts', 'tx_pkts', 'rx_byts', 'tx_byts',
                   're_pkts', 'exits', 'tpkt_per_exit']

    for i in range(int(params.get("queues", 0))):
        record_list.append('rx_intr_%s' % i)
    record_list.append('rx_intr_sum')
    for i in range(int(params.get("queues", 0))):
        record_list.append('tx_intr_%s' % i)
    record_list.append('tx_intr_sum')
    base = params.get("format_base", "12")
    fbase = params.get("format_fbase", "2")

    output = ssh_cmd(host, "mpstat 1 1 |grep CPU")
    mpstat_head = re.findall(r"CPU\s+.*", output)[0].split()
    mpstat_key = params.get("mpstat_key", "%idle")
    if mpstat_key in mpstat_head:
        mpstat_index = mpstat_head.index(mpstat_key) + 1
    else:
        mpstat_index = 0

    for protocol in protocols.split():
        error_context.context("Testing %s protocol" % protocol, logging.info)
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
                elif (protocol == "TCP_MAERTS"):
                    nf_args = "-C -c -t %s -- -m ,%s" % (protocol, i)
                else:
                    nf_args = "-C -c -t %s -- -m %s" % (protocol, i)

                ret = launch_client(j, server, server_ctl, host, clients,
                                    test_duration, nf_args, netserver_port,
                                    params, server_cyg, test)

                thu = float(ret['thu'])
                cpu = 100 - float(ret['mpstat'].split()[mpstat_index])
                normal = thu / cpu
                if ret.get('tx_pkt') and ret.get('exits'):
                    ret['tpkt_per_exit'] = float
                    (ret['tx_pkts']) / float(ret['exits'])

                ret['size'] = int(i)
                ret['sessions'] = int(j)
                if protocol in ("TCP_RR", "TCP_CRR"):
                    ret['trans.rate'] = thu
                else:
                    ret['throughput'] = thu
                ret['CPU'] = cpu
                ret['thr_per_CPU'] = normal
                row, key_list = netperf_record(ret, record_list,
                                               header=record_header,
                                               base=base,
                                               fbase=fbase)
                if record_header:
                    record_header = False
                    category = row.split('\n')[0]

                test.write_test_keyval({'category': category})
                prefix = '%s--%s--%s' % (protocol, i, j)
                for key in key_list:
                    test.write_test_keyval(
                        {'%s--%s' % (prefix, key): ret[key]})

                logging.info(row)
                fd.write(row + "\n")

                fd.flush()

                logging.debug("Remove temporary files")
                process.system_output("rm -f /tmp/netperf.%s.nf" % ret['pid'],
                                      verbose=False, ignore_status=True,
                                      shell=True)
                logging.info("Netperf thread completed successfully")
    fd.close()


def ssh_cmd(session, cmd, timeout=120, ignore_status=False):
    """
    Execute remote command and return the output

    :param session: a remote shell session or tag for localhost
    :param cmd: executed command
    :param timeout: timeout for the command
    """
    if session == "localhost":
        o = process.system_output(cmd, timeout=timeout,
                                  ignore_status=ignore_status,
                                  shell=True).decode()
    else:
        o = session.cmd(cmd, timeout=timeout, ignore_all_errors=ignore_status)
    return o


@error_context.context_aware
def launch_client(sessions, server, server_ctl, host, clients, l, nf_args,
                  port, params, server_cyg, test):
    """ Launch netperf clients """

    netperf_version = params.get("netperf_version", "2.6.0")
    client_path = "/tmp/netperf-%s/src/netperf" % netperf_version
    server_path = "/tmp/netperf-%s/src/netserver" % netperf_version
    get_status_flag = params.get("get_status_in_guest", "no") == "yes"
    global _netserver_started
    # Start netserver
    if _netserver_started:
        logging.debug("Netserver already started.")
    else:
        error_context.context("Start Netserver on guest", logging.info)
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
                logging.info("Start netserver with cygwin, cmd is: %s" %
                             netserv_start_cmd)
                if "netserver" not in server_ctl.cmd_output("tasklist"):
                    netperf_pack = "netperf-%s" % params.get("netperf_version")
                    s_check_cmd = "dir %s" % netserver_path
                    p_check_cmd = "dir %s" % cygwin_root
                    if not ("netserver.exe" in server_ctl.cmd(s_check_cmd) and
                            netperf_pack in server_ctl.cmd(p_check_cmd)):
                        error_context.context(
                            "Install netserver in Windows guest cygwin",
                            logging.info)
                        cmd = "xcopy %s %s /S /I /Y" % (
                            netperf_src, cygwin_root)
                        server_ctl.cmd(cmd)
                        server_cyg.cmd_output(
                            netperf_install_cmd, timeout=timeout)
                        if "netserver.exe" not in server_ctl.cmd(s_check_cmd):
                            err_msg = "Install netserver cygwin failed"
                            test.error(err_msg)
                        logging.info(
                            "Install netserver in cygwin successfully")
            else:
                start_session = server_ctl
                netserv_start_cmd = params.get("netserv_start_cmd") % cdrom_drv
                logging.info("Start netserver without cygwin, cmd is: %s" %
                             netserv_start_cmd)

            error_context.context("Start netserver on windows guest",
                                  logging.info)
            start_netserver_win(start_session, netserv_start_cmd, test)

        else:
            logging.info("Netserver start cmd is '%s'" % server_path)
            ssh_cmd(server_ctl, "pidof netserver || %s" % server_path)
            ncpu = ssh_cmd(server_ctl,
                           "cat /proc/cpuinfo |grep processor |wc -l")
            ncpu = re.findall(r"\d+", ncpu)[-1]

        logging.info("Netserver start successfully")

    def count_interrupt(name):
        """
        Get a list of interrut number for each queue

        @param name: the name of interrupt, such as "virtio0-input"
        """
        sum = 0
        intr = []
        stat = ssh_cmd(server_ctl, "grep %s /proc/interrupts" % name)
        for i in stat.strip().split("\n"):
            for cpu in range(int(ncpu)):
                sum += int(i.split()[cpu + 1])
            intr.append(sum)
            sum = 0
        return intr

    def get_state():
        for i in ssh_cmd(server_ctl, "ifconfig").split("\n\n"):
            if server in i:
                ifname = re.findall(r"(\w+\d+)[:\s]", i)[0]

        path = "find /sys/devices|grep net/%s/statistics" % ifname
        cmd = "%s/rx_packets|xargs cat;%s/tx_packets|xargs cat;" \
            "%s/rx_bytes|xargs cat;%s/tx_bytes|xargs cat" % (path,
                                                             path, path, path)
        output = ssh_cmd(server_ctl, cmd).split()[-4:]

        nrx = int(output[0])
        ntx = int(output[1])
        nrxb = int(output[2])
        ntxb = int(output[3])

        nre = int(ssh_cmd(server_ctl, "grep Tcp /proc/net/snmp|tail -1"
                          ).split()[12])
        state_list = ['rx_pkts', nrx, 'tx_pkts', ntx, 'rx_byts', nrxb,
                      'tx_byts', ntxb, 're_pkts', nre]
        try:
            nrx_intr = count_interrupt("virtio.-input")
            ntx_intr = count_interrupt("virtio.-output")
            sum = 0
            for i in range(len(nrx_intr)):
                state_list.append('rx_intr_%s' % i)
                state_list.append(nrx_intr[i])
                sum += nrx_intr[i]
            state_list.append('rx_intr_sum')
            state_list.append(sum)

            sum = 0
            for i in range(len(ntx_intr)):
                state_list.append('tx_intr_%s' % i)
                state_list.append(ntx_intr[i])
                sum += ntx_intr[i]
            state_list.append('tx_intr_sum')
            state_list.append(sum)

        except IndexError:
            ninit = count_interrupt("virtio.")
            state_list.append('intr')
            state_list.append(ninit)

        exits = int(ssh_cmd(host, "cat /sys/kernel/debug/kvm/exits"))
        state_list.append('exits')
        state_list.append(exits)

        return state_list

    def netperf_thread(i, numa_enable, client_s, timeout):
        cmd = ""
        fname = "/tmp/netperf.%s.nf" % pid
        if numa_enable:
            n = abs(int(params.get("numa_node"))) - 1
            cmd += "numactl --cpunodebind=%s --membind=%s " % (n, n)
        cmd += "`command -v python python3 ` "
        cmd += "/tmp/netperf_agent.py %d %s -D 1 -H %s -l %s %s" % (
               i, client_path, server, int(l) * 1.5, nf_args)
        cmd += " >> %s" % fname
        logging.info("Start netperf thread by cmd '%s'" % cmd)
        ssh_cmd(client_s, cmd)

    def all_clients_up():
        try:
            content = ssh_cmd(clients[-1], "cat %s" % fname)
        except:
            content = ""
            return False
        if int(sessions) == len(re.findall("MIGRATE", content)):
            return True
        return False

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
            test.error("We couldn't expect this parallism, expect %s get %s"
                       % (sessions, nresult))

        niteration = nresult // sessions
        result = 0.0
        for this in lines[-sessions * niteration:]:
            if "Interim" in this:
                result += float(re.findall(r"Interim result: *(\S+)", this)[0])
        result = result / niteration
        logging.debug("niteration: %s" % niteration)
        return result

    error_context.context("Start netperf client threads", logging.info)
    pid = str(os.getpid())
    fname = "/tmp/netperf.%s.nf" % pid
    ssh_cmd(clients[-1], "rm -f %s" % fname)
    numa_enable = params.get("netperf_with_numa", "yes") == "yes"
    timeout_netperf_start = int(l) * 0.5
    client_thread = threading.Thread(target=netperf_thread,
                                     kwargs={"i": int(sessions),
                                             "numa_enable": numa_enable,
                                             "client_s": clients[0],
                                             "timeout": timeout_netperf_start})
    client_thread.start()

    ret = {}
    ret['pid'] = pid

    if utils_misc.wait_for(all_clients_up, timeout_netperf_start, 0.0, 0.2,
                           "Wait until all netperf clients start to work"):
        logging.debug("All netperf clients start to work.")
    else:
        test.fail("Error, not all netperf clients at work")

    # real & effective test starts
    if get_status_flag:
        start_state = get_state()
    ret['mpstat'] = ssh_cmd(host, "mpstat 1 %d |tail -n 1" % (l - 1))
    finished_result = ssh_cmd(clients[-1], "cat %s" % fname)

    # stop netperf clients
    kill_cmd = "killall netperf"
    if params.get("os_type") == "windows":
        kill_cmd = "taskkill /F /IM netperf*"
    ssh_cmd(clients[-1], kill_cmd, ignore_status=True)

    # real & effective test ends
    if get_status_flag:
        end_state = get_state()
        if len(start_state) != len(end_state):
            msg = "Initial state not match end state:\n"
            msg += "  start state: %s\n" % start_state
            msg += "  end state: %s\n" % end_state
            logging.warn(msg)
        else:
            for i in range(len(end_state) // 2):
                ret[end_state[i * 2]] = (end_state[i * 2 + 1] -
                                         start_state[i * 2 + 1])

    client_thread.join()

    error_context.context("Testing Results Treatment and Report", logging.info)
    f = open(fname, "w")
    f.write(finished_result)
    f.close()
    ret['thu'] = parse_demo_result(fname, int(sessions))
    return ret
