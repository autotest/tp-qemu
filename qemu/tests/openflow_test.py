import re
import time

from virttest import error_context, remote, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test Step:
        1. Boot up two virtual machine
        2. Set openflow rules
        3. Run ping test, nc(tcp, udp) test, check whether openflow rules take
           effect.
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    def run_tcpdump_bg(vm, addresses, dump_protocol):
        """
        Run tcpdump in background, tcpdump will exit once catch a packet
        match the rules.
        """
        bg_session = vm.wait_for_login()
        if tcpdump_is_alive(bg_session):
            bg_session.cmd("killall -9 tcpdump")
        tcpdump_cmd = (
            "setsid tcpdump -iany -n -v %s and 'src %s and dst %s'"
            " -c 1 >/dev/null 2>&1"
        )
        bg_session.sendline(tcpdump_cmd % (dump_protocol, addresses[0], addresses[1]))
        if not utils_misc.wait_for(
            lambda: tcpdump_is_alive(bg_session), 30, 0, 1, "Waiting tcpdump start..."
        ):
            test.cancel("Error, can not run tcpdump")
        bg_session.close()

    def dump_catch_data(session, dump_log, catch_reg):
        """
        Search data from dump_log
        """
        dump_info = session.cmd_output("cat %s" % dump_log)
        if re.findall(catch_reg, dump_info, re.I):
            return True
        return False

    def tcpdump_is_alive(session):
        """
        Check whether tcpdump is alive
        """
        if session.cmd_status("pidof tcpdump"):
            return False
        return True

    def tcpdump_catch_packet_test(session, drop_flow=False):
        """
        Check whether tcpdump catch match rules packets, once catch a packet
        match rules tcpdump will exit.
        when drop_flow is 'True', tcpdump couldn't catch any packets.
        """
        packet_receive = not tcpdump_is_alive(session)
        if packet_receive == drop_flow:
            err_msg = "Error, flow %s" % (drop_flow and "was" or "wasn't")
            err_msg += " dropped, tcpdump "
            err_msg += "%s " % (packet_receive and "can" or "can not")
            err_msg += "receive the packets"
            test.error(err_msg)
        test.log.info(
            "Correct, flow %s dropped, tcpdump %s receive the packet",
            (drop_flow and "was" or "was not"),
            (packet_receive and "can" or "can not"),
        )

    def arp_entry_clean(entry=None):
        """
        Clean arp catch in guest
        """
        if not entry:
            arp_clean_cmd = "arp -n | awk '/^[1-2]/{print \"arp -d \" $1}'|sh"
        else:
            arp_clean_cmd = "arp -d %s" % entry
        for session in sessions:
            session.cmd_output_safe(arp_clean_cmd)

    def check_arp_info(session, entry, vm, match_mac=None):
        arp_info = session.cmd_output("arp -n")
        arp_entries = [_ for _ in arp_info.splitlines() if re.match(entry, _)]

        match_string = match_mac or "incomplete"

        if not arp_entries:
            test.error("Can not find arp entry in %s: %s" % (vm.name, arp_info))

        if not re.findall(match_string, arp_entries[0], re.I):
            test.fail(
                "Can not find the mac address"
                " %s of %s in arp"
                " entry %s" % (match_mac, vm.name, arp_entries[0])
            )

    def ping_test(session, dst, drop_flow=False):
        """
        Ping test, check icmp
        """
        ping_status, ping_output = utils_test.ping(
            dest=dst, count=10, timeout=20, session=session
        )
        # when drop_flow is true, ping should failed(return not zero)
        # drop_flow is false, ping should success
        packets_lost = 100
        if ping_status and not drop_flow:
            test.error("Ping should success when not drop_icmp")
        elif not ping_status:
            packets_lost = utils_test.get_loss_ratio(ping_output)
            if drop_flow and packets_lost != 100:
                test.error("When drop_icmp, ping shouldn't works")
            if not drop_flow and packets_lost == 100:
                test.error("When not drop_icmp, ping should works")

        info_msg = "Correct, icmp flow %s dropped, ping '%s', "
        info_msg += "packets lost rate is: '%s'"
        test.log.info(
            info_msg,
            (drop_flow and "was" or "was not"),
            (ping_status and "failed" or "success"),
            packets_lost,
        )

    def run_ping_bg(vm, dst):
        """
        Run ping in background
        """
        ping_cmd = "ping %s" % dst
        session = vm.wait_for_login()
        test.log.info("Ping %s in background", dst)
        session.sendline(ping_cmd)
        return session

    def check_bg_ping(session):
        ping_pattern = r"\d+ bytes from \d+.\d+.\d+.\d+:"
        ping_pattern += r" icmp_seq=\d+ ttl=\d+ time=.*? ms"
        ping_failed_pattern = r"From .*? icmp_seq=\d+ Destination"
        ping_failed_pattern += r" Host Unreachable"
        try:
            out = session.read_until_output_matches([ping_pattern, ping_failed_pattern])
            if re.search(ping_failed_pattern, out[1]):
                return False, out[1]
            else:
                return True, out[1]
        except Exception as msg:
            return False, msg

    def file_transfer(sessions, addresses, timeout):
        prepare_cmd = "dd if=/dev/zero of=/tmp/copy_file count=1024 bs=1M"
        md5_cmd = "md5sum /tmp/copy_file"
        port = params.get("shell_port")
        prompt = params.get("shell_prompt")
        username = params.get("username")
        password = params.get("password")
        sessions[0].cmd(prepare_cmd, timeout=timeout)
        ori_md5 = sessions[0].cmd_output(md5_cmd)
        scp_cmd = (
            r"scp -v -o UserKnownHostsFile=/dev/null "
            r"-o StrictHostKeyChecking=no "
            r"-o PreferredAuthentications=password -r "
            r"-P %s /tmp/copy_file %s@\[%s\]:/tmp/copy_file"
            % (port, username, addresses[1])
        )
        sessions[0].sendline(scp_cmd)
        remote.handle_prompts(sessions[0], username, password, prompt, 600)
        new_md5 = sessions[1].cmd_output(md5_cmd)
        for session in sessions:
            session.cmd("rm -f /tmp/copy_file")
        if new_md5 != ori_md5:
            test.fail(
                "Md5 value changed after file transfer, "
                "original is %s and the new file"
                " is: %s" % (ori_md5, new_md5)
            )

    def nc_connect_test(
        sessions, addresses, drop_flow=False, nc_port="8899", udp_model=False
    ):
        """
        Nc connect test, check tcp and udp
        """
        nc_log = "/tmp/nc_log"
        server_cmd = "nc -l %s"
        client_cmd = "echo client | nc %s %s"
        if udp_model:
            server_cmd += " -u -w 3"
            client_cmd += " -u -w 3"
        server_cmd += " > %s &"
        client_cmd += " &"
        try:
            sessions[1].cmd_output_safe(server_cmd % (nc_port, nc_log))
            sessions[0].cmd_output_safe(client_cmd % (addresses[1], nc_port))

            nc_protocol = udp_model and "UDP" or "TCP"
            nc_connect = False
            if utils_misc.wait_for(
                lambda: dump_catch_data(sessions[1], nc_log, "client"),
                10,
                0,
                2,
                text="Wait '%s' connect" % nc_protocol,
            ):
                nc_connect = True
            if nc_connect == drop_flow:
                err_msg = "Error, '%s' " % nc_protocol
                err_msg += "flow %s " % (drop_flow and "was" or "was not")
                err_msg += "dropped, nc connect should"
                err_msg += " '%s'" % (nc_connect and "failed" or "success")
                test.error(err_msg)

            test.log.info(
                "Correct, '%s' flow %s dropped, and nc connect %s",
                nc_protocol,
                (drop_flow and "was" or "was not"),
                (nc_connect and "success" or "failed"),
            )
        finally:
            for session in sessions:
                session.cmd_output_safe("killall nc || killall ncat")
                session.cmd("%s %s" % (clean_cmd, nc_log), ignore_all_errors=True)

    def acl_rules_check(acl_rules, flow_options):
        flow_options = re.sub("action=", "actions=", flow_options)
        if "arp" in flow_options:
            flow_options = re.sub("nw_src=", "arp_spa=", flow_options)
            flow_options = re.sub("nw_dst=", "arp_tpa=", flow_options)
        acl_options = re.split(",", flow_options)
        for line in acl_rules.splitlines():
            rule = [_.lower() for _ in re.split("[ ,]", line) if _]
            item_in_rule = 0

            for acl_item in acl_options:
                if acl_item.lower() in rule:
                    item_in_rule += 1

            if item_in_rule == len(acl_options):
                return True
        return False

    def remove_plus_items(open_flow_rules):
        plus_items = ["duration", "n_packets", "n_bytes", "idle_age", "hard_age"]
        for plus_item in plus_items:
            open_flow_rules = re.sub("%s=.*?," % plus_item, "", open_flow_rules)
        return open_flow_rules

    br_name = params.get("netdst", "ovs0")
    timeout = int(params.get("login_timeout", "360"))
    prepare_timeout = int(params.get("prepare_timeout", "360"))
    clean_cmd = params.get("clean_cmd", "rm -f")
    sessions = []
    addresses = []
    vms = []
    bg_ping_session = None

    if not utils_net.ovs_br_exists(br_name):
        test.cancel("%s isn't an openvswith bridge" % br_name)

    error_context.context("Init boot the vms")
    for vm_name in params.objects("vms"):
        vms.append(env.get_vm(vm_name))
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=timeout))
        addresses.append(vm.get_address())

    # set openflow rules:
    f_protocol = params.get("flow", "arp")
    f_base_options = "%s,nw_src=%s,nw_dst=%s" % (f_protocol, addresses[0], addresses[1])
    for session in sessions:
        session.cmd(
            "systemctl stop firewalld || service firewalld stop", ignore_all_errors=True
        )

    try:
        for drop_flow in [True, False]:
            if drop_flow:
                f_command = "add-flow"
                f_options = f_base_options + ",action=drop"
                drop_icmp = eval(params.get("drop_icmp", "True"))
                drop_tcp = eval(params.get("drop_tcp", "True"))
                drop_udp = eval(params.get("drop_udp", "True"))
            else:
                f_command = "mod-flows"
                f_options = f_base_options + ",action=normal"
                drop_icmp = False
                drop_tcp = False
                drop_udp = False

            error_context.base_context("Test prepare")
            error_context.context("Do %s %s on %s" % (f_command, f_options, br_name))
            utils_net.openflow_manager(br_name, f_command, f_options)
            acl_rules = utils_net.openflow_manager(
                br_name, "dump-flows"
            ).stdout.decode()
            if not acl_rules_check(acl_rules, f_options):
                test.fail("Can not find the rules from" " ovs-ofctl: %s" % acl_rules)

            error_context.context(
                "Run tcpdump in guest %s" % vms[1].name, test.log.info
            )
            run_tcpdump_bg(vms[1], addresses, f_protocol)

            if drop_flow or f_protocol != "arp":
                error_context.context("Clean arp cache in both guest", test.log.info)
                arp_entry_clean(addresses[1])

            error_context.base_context(
                "Exec '%s' flow '%s' test"
                % (f_protocol, drop_flow and "drop" or "normal")
            )
            if drop_flow:
                error_context.context(
                    "Ping test form %s to %s" % (vms[0].name, vms[1].name),
                    test.log.info,
                )
                ping_test(sessions[0], addresses[1], drop_icmp)
                if params.get("run_file_transfer") == "yes":
                    error_context.context(
                        "Transfer file form %s to %s" % (vms[0].name, vms[1].name),
                        test.log.info,
                    )
                    file_transfer(sessions, addresses, prepare_timeout)
            else:
                error_context.context(
                    "Ping test form %s to %s in background"
                    % (vms[0].name, vms[1].name),
                    test.log.info,
                )
                bg_ping_session = run_ping_bg(vms[0], addresses[1])

            if f_protocol == "arp" and drop_flow:
                error_context.context(
                    "Check arp inside %s" % vms[0].name, test.log.info
                )
                check_arp_info(sessions[0], addresses[1], vms[0])
            elif f_protocol == "arp" or params.get("check_arp") == "yes":
                time.sleep(2)
                error_context.context("Check arp inside guests.", test.log.info)
                for index, address in enumerate(addresses):
                    sess_index = (index + 1) % 2
                    mac = vms[index].virtnet.get_mac_address(0)
                    check_arp_info(sessions[sess_index], address, vms[index], mac)

            error_context.context("Run nc connect test via tcp", test.log.info)
            nc_connect_test(sessions, addresses, drop_tcp)

            error_context.context("Run nc connect test via udp", test.log.info)
            nc_connect_test(sessions, addresses, drop_udp, udp_model=True)

            error_context.context("Check tcpdump data catch", test.log.info)
            tcpdump_catch_packet_test(sessions[1], drop_flow)
    finally:
        openflow_rules_ori = utils_net.openflow_manager(
            br_name, "dump-flows"
        ).stdout.decode()
        openflow_rules_ori = remove_plus_items(openflow_rules_ori)
        utils_net.openflow_manager(br_name, "del-flows", f_protocol)
        openflow_rules = utils_net.openflow_manager(
            br_name, "dump-flows"
        ).stdout.decode()
        openflow_rules = remove_plus_items(openflow_rules)
        removed_rule = list(
            set(openflow_rules_ori.splitlines()) - set(openflow_rules.splitlines())
        )

        if f_protocol == "tcp":
            error_context.context("Run nc connect test via tcp", test.log.info)
            nc_connect_test(sessions, addresses)
        elif f_protocol == "udp":
            error_context.context("Run nc connect test via udp", test.log.info)
            nc_connect_test(sessions, addresses, udp_model=True)

        for session in sessions:
            session.close()
        failed_msg = []
        if not removed_rule or not acl_rules_check(removed_rule[0], f_options):
            failed_msg.append("Failed to delete %s" % f_options)
        if bg_ping_session:
            bg_ping_ok = check_bg_ping(bg_ping_session)
            bg_ping_session.close()
            if not bg_ping_ok[0]:
                failed_msg.append(
                    "There is something wrong happen in "
                    "background ping: %s" % bg_ping_ok[1]
                )

        if failed_msg:
            test.fail(failed_msg)
