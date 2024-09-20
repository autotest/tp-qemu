import random
import re
import time

from virttest import error_context, utils_misc, utils_net, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test failover by team driver

    1) Boot a vm with 4 nics.
    2) inside guest, configure the team driver.
    3) inside guest, ping host
    4) inside guest, repeated down the slaves one by one.
    5) check ping_result.

    :param test: Kvm test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def team_port_add(ifnames, team_if):
        """Team0 add ports and return the ip link result for debuging"""
        for port in ifnames:
            session_serial.cmd_output_safe(params["clearip_cmd"] % port)
            session_serial.cmd_output_safe(params["setdown_cmd"] % port)
            session_serial.cmd_output_safe(params["addport_cmd"] % port)
        output_teamnl = session_serial.cmd_output_safe(params["portchk_cmd"])
        ports = re.findall(r"%s" % params["ptn_teamnl"], output_teamnl)
        for port in ifnames:
            if port not in ports:
                test.fail("Add %s to %s failed." % (port, team_if))
        session_serial.cmd_output_safe(params["killdhclient_cmd"])
        output = session_serial.cmd_output_safe(params["getip_cmd"], timeout=300)
        team_ip = re.search(r"%s" % params["ptn_ipv4"], output).group()
        if not team_ip:
            test.fail("Failed to get ip address of %s" % team_if)
        return ports, team_ip

    def failover(ifnames, timeout):
        """func for failover"""
        time.sleep(3)
        starttime = time.time()
        while True:
            pid_ping = session_serial.cmd_output_safe("pidof ping")
            pid = re.findall(r"(\d+)", pid_ping)
            if not pid:
                break
                # if ping finished, will break the loop.
            for port in ifnames:
                session_serial.cmd_output_safe(params["setdown_cmd"] % port)
                time.sleep(random.randint(5, 30))
                session_serial.cmd_output_safe(params["setup_cmd"] % port)
            endtime = time.time()
            timegap = endtime - starttime
            if timegap > timeout:
                break

    def check_ping(status, output):
        """ratio <5% is acceptance."""
        if status != 0:
            test.fail("Ping failed, staus:%s, output:%s" % (status, output))
        # if status != 0 the ping process seams hit issue.
        ratio = utils_test.get_loss_ratio(output)
        if ratio == -1:
            test.fail(
                "The ratio is %s, and status is %s, "
                "output is %s" % (ratio, status, output)
            )
        elif ratio > int(params["failed_ratio"]):
            test.fail("The loss raito is %s, test failed" % ratio)
        test.log.info(
            "ping pass with loss raito:%s, that less than %s",
            ratio,
            params["failed_ratio"],
        )

    def team_if_exist():
        """judge if team is alive well."""
        team_exists_cmd = params.get("team_if_exists_cmd")
        return session_serial.cmd_status(team_exists_cmd, safe=True) == 0

    if params["netdst"] not in utils_net.Bridge().list_br():
        test.cancel("Host does not use Linux Bridge")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 1200))
    session_serial = vm.wait_for_serial_login(timeout=timeout)
    ifnames = [
        utils_net.get_linux_ifname(session_serial, vm.get_mac_address(vlan))
        for vlan, nic in enumerate(vm.virtnet)
    ]
    session_serial.cmd_output_safe(params["nm_stop_cmd"])
    team_if = params.get("team_if")
    # initial

    error_context.context("Step1: Configure the team environment", test.log.info)
    # steps of building the teaming environment starts
    modprobe_cmd = "modprobe team"
    session_serial.cmd_output_safe(modprobe_cmd)
    session_serial.cmd_output_safe(params["createteam_cmd"])
    # this cmd is to create the team0 and correspoding userspace daemon
    if not team_if_exist():
        test.fail("Interface %s is not created." % team_if)
    # check if team0 is created successfully
    ports, team_ip = team_port_add(ifnames, team_if)
    test.log.debug("The list of the ports that added to %s : %s", team_if, ports)
    test.log.debug("The ip address of %s : %s", team_if, team_ip)
    output = session_serial.cmd_output_safe(params["team_debug_cmd"])
    test.log.debug("team interface configuration: %s", output)
    route_cmd = session_serial.cmd_output_safe(params["route_cmd"])
    test.log.debug("The route table of guest: %s", route_cmd)
    # this is not this case checkpoint, just to check if route works fine
    # steps of building finished

    try:
        error_context.context("Login in guest via ssh", test.log.info)
        # steps of testing this case starts
        session = vm.wait_for_login(timeout=timeout)
        dest = utils_net.get_ip_address_by_interface(params["netdst"])
        count = params.get("count")
        timeout = float(count) * 2
        error_context.context("Step2: Check if guest can ping out:", test.log.info)
        status, output = utils_test.ping(
            dest=dest, count=10, interface=team_if, timeout=30, session=session
        )
        check_ping(status, output)
        # small ping check if the team0 works w/o failover
        error_context.context(
            "Step3: Start failover testing until " "ping finished", test.log.info
        )
        failover_thread = utils_misc.InterruptedThread(failover, (ifnames, timeout))
        failover_thread.start()
        # start failover loop until ping finished
        error_context.context(
            "Step4: Start ping host for %s counts" % count, test.log.info
        )
        if failover_thread.is_alive():
            status, output = utils_test.ping(
                dest=dest,
                count=count,
                interface=team_if,
                timeout=float(count) * 1.5,
                session=session,
            )
            error_context.context("Step5: Check if ping succeeded", test.log.info)
            check_ping(status, output)
        else:
            test.error("The failover thread is not alive")
        time.sleep(3)
        try:
            timeout = timeout * 1.5
            failover_thread.join(timeout)
        except Exception:
            test.error("Failed to join the failover thread")
        # finish the main steps and check the result
        session_serial.cmd_output_safe(params["killteam_cmd"])
        if team_if_exist():
            test.fail("Remove %s failed" % team_if)
        test.log.info("%s removed", team_if)
        # remove the team0 and the daemon, check if succeed
    finally:
        if session:
            session.close()
