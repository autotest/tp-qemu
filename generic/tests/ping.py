from avocado.utils import process
from virttest import error_context, utils_net, utils_test


def _ping_with_params(
    test,
    params,
    dest,
    interface=None,
    packet_size=None,
    interval=None,
    count=0,
    session=None,
    flood=False,
):
    if flood:
        cmd = "ping " + dest + " -f -q"
        if interface:
            cmd += " -S %s" % interface
        flood_minutes = float(params.get("flood_minutes", 10))
        status, output = utils_net.raw_ping(
            cmd, flood_minutes * 60, session, test.log.debug
        )
    else:
        timeout = float(count) * 1.5
        status, output = utils_net.ping(
            dest,
            count,
            interval,
            interface,
            packet_size,
            session=session,
            timeout=timeout,
        )
    if status != 0:
        test.fail("Ping failed, status: %s," " output: %s" % (status, output))
    if params.get("strict_check", "no") == "yes":
        ratio = utils_test.get_loss_ratio(output)
        if ratio != 0:
            test.fail("Loss ratio is %s" % ratio)


@error_context.context_aware
def run(test, params, env):
    """
    Ping the guest with different size of packets.

    1) Login to guest
    2) Ping test on nic(s) from host - default_ping/multi_nics
        2.1) Ping with packet size from 0 to 65507
        2.2) Flood ping test
        2.3) Ping test after flood ping, Check if the network is still alive
    3) Ping test from guest side to external host - ext_host
        3.1) Ping with packet size from 0 to 65507 (win guest is up to 65500)
        3.2) Flood ping test
        3.3) Ping test after flood ping, Check if the network is still alive

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    counts = params.get("ping_counts", 30)
    packet_sizes = params.get("packet_size", "").split()
    interval_times = params.get("interval_time", "1").split()
    timeout = int(params.get("login_timeout", 360))
    ping_ext_host = params.get("ping_ext_host", "no") == "yes"
    pre_cmd = params.get("pre_cmd", None)
    vm = env.get_vm(params["main_vm"])
    serial_status = params.get_boolean("serial_login")

    error_context.context("Login to guest", test.log.info)
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout, serial=serial_status)

    # get the test ip, interface & session
    dest_ips = []
    sessions = []
    interfaces = []
    if ping_ext_host:
        ext_host = params.get("ext_host", "")
        ext_host_get_cmd = params.get("ext_host_get_cmd", "")
        if ext_host_get_cmd:
            try:
                ext_host = process.system_output(ext_host_get_cmd, shell=True)
                ext_host = ext_host.decode()
            except process.CmdError:
                test.log.warning(
                    "Can't get specified host with cmd '%s',"
                    " Fallback to default host '%s'",
                    ext_host_get_cmd,
                    ext_host,
                )
        dest_ips = [ext_host]
        sessions = [session]
        interfaces = [None]
    else:
        # most of linux distribution don't add IP configuration for extra nics,
        # so get IP for extra nics via pre_cmd;
        if pre_cmd:
            session.cmd(pre_cmd, timeout=600)
        for i, nic in enumerate(vm.virtnet):
            ip = vm.get_address(i)
            if ip.upper().startswith("FE80"):
                interface = utils_net.get_neigh_attch_interface(ip)
            else:
                interface = None
            nic_name = nic.get("nic_name")
            if not ip:
                test.fail("Could not get the ip of nic index %d: %s", i, nic_name)
            dest_ips.append(ip)
            sessions.append(None)
            interfaces.append(interface)

    for ip, interface, session in zip(dest_ips, interfaces, sessions):
        error_context.context("Ping test with dest: %s" % ip, test.log.info)

        # ping with different size & interval
        for size in packet_sizes:
            for interval in interval_times:
                test.log.info(
                    "Ping with packet size: %s and interval: %s", size, interval
                )
                _ping_with_params(
                    test,
                    params,
                    ip,
                    interface,
                    size,
                    interval,
                    session=session,
                    count=counts,
                )

        # ping with flood
        if params.get_boolean("flood_ping"):
            if not ping_ext_host or params.get("os_type") == "linux":
                error_context.context("Flood ping test", test.log.info)
                _ping_with_params(
                    test, params, ip, interface, session=session, flood=True
                )

                # ping to check whether the network is alive
                error_context.context(
                    "Ping test after flood ping,"
                    " Check if the network is still alive",
                    test.log.info,
                )
                _ping_with_params(
                    test, params, ip, interface, session=session, count=counts
                )
