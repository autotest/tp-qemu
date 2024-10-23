import os
import re

import aexpect
from avocado.utils import process
from virttest import utils_test


def run(test, params, env):
    """
    Test multicast function of nic (rtl8139/e1000/virtio)

    1) Create a VM.
    2) Join guest into multicast groups.
    3) Ping multicast addresses on host.
    4) Flood ping test with different size of packets.
    5) Final ping test and check if lose packet.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    def run_guest(cmd):
        try:
            session.cmd(cmd)
        except aexpect.ShellError as e:
            test.log.warning(e)

    def run_host_guest(cmd):
        run_guest(cmd)
        process.system(cmd, ignore_status=True, shell=True)

    # flush the firewall rules
    cmd_flush = "iptables -F"
    cmd_selinux = (
        "if [ -e /selinux/enforce ]; then setenforce 0; "
        "else echo 'no /selinux/enforce file present'; fi"
    )
    run_host_guest(cmd_flush)
    run_host_guest(cmd_selinux)
    # make sure guest replies to broadcasts
    cmd_broadcast = "echo 0 > /proc/sys/net/ipv4/icmp_echo_ignore_broadcasts"
    cmd_broadcast_2 = "echo 0 > /proc/sys/net/ipv4/icmp_echo_ignore_all"
    run_guest(cmd_broadcast)
    run_guest(cmd_broadcast_2)

    # base multicast address
    mcast = params.get("mcast", "225.0.0.1")
    # count of multicast addresses, less than 20
    mgroup_count = int(params.get("mgroup_count", 5))
    flood_minutes = float(params.get("flood_minutes", 10))
    ifname = vm.get_ifname()
    prefix = re.findall(r"\d+.\d+.\d+", mcast)[0]
    suffix = int(re.findall(r"\d+", mcast)[-1])
    # copy python script to guest for joining guest to multicast groups
    mcast_path = os.path.join(test.virtdir, "scripts/multicast_guest.py")
    vm.copy_files_to(mcast_path, "/tmp")
    output = session.cmd_output(
        "python /tmp/multicast_guest.py %d %s %d" % (mgroup_count, prefix, suffix)
    )

    # if success to join multicast, the process will be paused, and return PID.
    try:
        pid = re.findall(r"join_mcast_pid:(\d+)", output)[0]
    except IndexError:
        test.fail("Can't join multicast groups,output:%s" % output)

    try:
        for i in range(mgroup_count):
            new_suffix = suffix + i
            mcast = "%s.%d" % (prefix, new_suffix)

            test.log.info("Initial ping test, mcast: %s", mcast)
            s, o = utils_test.ping(mcast, 10, interface=ifname, timeout=20)
            if s != 0:
                test.fail(" Ping return non-zero value %s" % o)

            test.log.info("Flood ping test, mcast: %s", mcast)
            utils_test.ping(
                mcast,
                None,
                interface=ifname,
                flood=True,
                output_func=None,
                timeout=flood_minutes * 60,
            )

            test.log.info("Final ping test, mcast: %s", mcast)
            s, o = utils_test.ping(mcast, 10, interface=ifname, timeout=20)
            if s != 0:
                test.fail("Ping failed, status: %s, output: %s" % (s, o))

    finally:
        test.log.debug(session.cmd_output("ipmaddr show"))
        session.cmd_output("kill -s SIGCONT %s" % pid)
        session.close()
