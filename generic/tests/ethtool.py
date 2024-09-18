import re

import aexpect
from avocado.utils import crypto, process
from virttest import error_context, remote, utils_misc, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Test offload functions of ethernet device using ethtool

    1) Log into a guest.
    2) Saving ethtool configuration.
    3) Enable sub function of NIC.
    4) Execute callback function.
    5) Disable sub function of NIC.
    6) Run callback function again.
    7) Run file transfer test.
       7.1) Creating file in source host.
       7.2) Listening network traffic with tcpdump command.
       7.3) Transfer file.
       7.4) Comparing md5sum of the files on guest and host.
    8) Repeat step 3 - 7.
    9) Restore original configuration.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    @todo: Not all guests have ethtool installed, so
        find a way to get it installed using yum/apt-get/
        whatever
    """

    def ethtool_get(session):
        feature_pattern = {
            "tx": "tx.*checksumming",
            "rx": "rx.*checksumming",
            "sg": "scatter.*gather",
            "tso": "tcp.*segmentation.*offload",
            "gso": "generic.*segmentation.*offload",
            "gro": "generic.*receive.*offload",
            "lro": "large.*receive.*offload",
        }

        o = session.cmd("ethtool -k %s" % ethname)
        status = {}
        for f in feature_pattern.keys():
            try:
                temp = re.findall("%s: (.*)" % feature_pattern.get(f), o)[0]
                if temp.find("[fixed]") != -1:
                    test.log.debug("%s is fixed", f)
                    continue
                status[f] = temp
            except IndexError:
                status[f] = None
                test.log.debug("(%s) failed to get status '%s'", ethname, f)

        test.log.debug("(%s) offload status: '%s'", ethname, str(status))
        return status

    def ethtool_set(session, status):
        """
        Set ethernet device offload status

        :param status: New status will be changed to
        """
        txt = "Set offload status for device "
        txt += "'%s': %s" % (ethname, str(status))
        error_context.context(txt, test.log.info)

        cmd = "ethtool -K %s " % ethname
        cmd += " ".join([o + " " + s for o, s in status.items()])
        err_msg = "Failed to set offload status for device '%s'" % ethname
        try:
            session.cmd_output_safe(cmd)
        except aexpect.ShellCmdError as e:
            test.log.error("%s, detail: %s", err_msg, e)
            return False

        curr_status = dict(
            (k, v) for k, v in ethtool_get(session).items() if k in status.keys()
        )
        if curr_status != status:
            test.log.error(
                "%s, got: '%s', expect: '%s'", err_msg, str(curr_status), str(status)
            )
            return False

        return True

    def ethtool_save_params(session):
        error_context.context("Saving ethtool configuration", test.log.info)
        return ethtool_get(session)

    def ethtool_restore_params(session, status):
        cur_stat = ethtool_get(session)
        if cur_stat != status:
            error_context.context("Restoring ethtool configuration", test.log.info)
            ethtool_set(session, status)

    def compare_md5sum(name):
        txt = "Comparing md5sum of the files on guest and host"
        error_context.context(txt, test.log.info)
        host_result = crypto.hash_file(name, algorithm="md5")
        try:
            o = session.cmd_output("md5sum %s" % name)
            guest_result = re.findall(r"\w+", o)[0]
        except IndexError:
            test.log.error("Could not get file md5sum in guest")
            return False
        test.log.debug("md5sum: guest(%s), host(%s)", guest_result, host_result)
        return guest_result == host_result

    def transfer_file(src):
        """
        Transfer file by scp, use tcpdump to capture packets, then check the
        return string.

        :param src: Source host of transfer file
        :return: Tuple (status, error msg/tcpdump result)
        """
        sess = vm.wait_for_login(timeout=login_timeout)
        session.cmd_output("rm -rf %s" % filename)
        dd_cmd = "dd if=/dev/urandom of=%s bs=1M count=%s" % (
            filename,
            params.get("filesize"),
        )
        failure = (False, "Failed to create file using dd, cmd: %s" % dd_cmd)
        txt = "Creating file in source host, cmd: %s" % dd_cmd
        error_context.context(txt, test.log.info)
        ethname = utils_net.get_linux_ifname(session, vm.get_mac_address(0))
        tcpdump_cmd = "tcpdump -lep -i %s -s 0 tcp -vv port ssh" % ethname
        if src == "guest":
            tcpdump_cmd += " and src %s" % guest_ip
            copy_files_func = vm.copy_files_from
            try:
                sess.cmd_output(dd_cmd, timeout=360)
            except aexpect.ShellCmdError:
                return failure
        else:
            tcpdump_cmd += " and dst %s" % guest_ip
            copy_files_func = vm.copy_files_to
            try:
                process.system(dd_cmd, shell=True)
            except process.CmdError:
                return failure

        # only capture the new tcp port after offload setup
        original_tcp_ports = re.findall(
            r"tcp.*:(\d+).*%s" % guest_ip,
            process.system_output("/bin/netstat -nap").decode(),
        )

        for i in original_tcp_ports:
            tcpdump_cmd += " and not port %s" % i

        txt = "Listening traffic using command: %s" % tcpdump_cmd
        error_context.context(txt, test.log.info)
        sess.sendline(tcpdump_cmd)
        if not utils_misc.wait_for(
            lambda: session.cmd_status("pgrep tcpdump") == 0, 30
        ):
            return (False, "Tcpdump process wasn't launched")

        txt = "Transferring file %s from %s" % (filename, src)
        error_context.context(txt, test.log.info)
        try:
            copy_files_func(filename, filename)
        except remote.SCPError as e:
            return (False, "File transfer failed (%s)" % e)

        session.cmd("killall tcpdump")
        try:
            tcpdump_string = sess.read_up_to_prompt(timeout=60)
        except aexpect.ExpectError:
            return (False, "Failed to read tcpdump's output")

        if not compare_md5sum(filename):
            return (False, "Failure, md5sum mismatch")
        return (True, tcpdump_string)

    def tx_callback(status="on"):
        s, o = transfer_file("guest")
        if not s:
            test.log.error(o)
            return False
        return True

    def rx_callback(status="on"):
        s, o = transfer_file("host")
        if not s:
            test.log.error(o)
            return False
        return True

    def so_callback(status="on"):
        s, o = transfer_file("guest")
        if not s:
            test.log.error(o)
            return False
        error_context.context("Check if contained large frame", test.log.info)
        # MTU: default IPv4 MTU is 1500 Bytes, ethernet header is 14 Bytes
        return (status == "on") ^ (
            len([i for i in re.findall(r"length (\d*):", o) if int(i) > mtu]) == 0
        )

    def ro_callback(status="on"):
        s, o = transfer_file("host")
        if not s:
            test.log.error(o)
            return False
        return True

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    error_context.context("Log into a guest.", test.log.info)
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    # Let's just error the test if we identify that there's no ethtool
    # installed
    error_context.context("Check whether ethtool installed in guest.")
    session.cmd("ethtool -h")
    mtu = 1514
    pretest_status = {}
    filename = "/tmp/ethtool.dd"
    guest_ip = vm.get_address()
    error_context.context("Try to get ethernet device name in guest.")
    ethname = utils_net.get_linux_ifname(session, vm.get_mac_address(0))

    supported_features = params.get("supported_features")
    if supported_features:
        supported_features = supported_features.split()
    else:
        test.error("No supported features set on the parameters")

    test_matrix = {
        # 'type: (callback,    (dependence), (exclude)'
        "tx": (tx_callback, (), ()),
        "rx": (rx_callback, (), ()),
        "sg": (tx_callback, ("tx",), ()),
        "tso": (
            so_callback,
            (
                "tx",
                "sg",
            ),
            ("gso",),
        ),
        "gso": (so_callback, (), ("tso",)),
        "gro": (ro_callback, ("rx",), ("lro",)),
        "lro": (rx_callback, (), ("gro",)),
    }
    pretest_status = ethtool_save_params(session)
    failed_tests = []
    try:
        for f_type in supported_features:
            callback = test_matrix[f_type][0]

            offload_stat = {f_type: "on"}
            offload_stat.update(dict.fromkeys(test_matrix[f_type][1], "on"))
            # lro is fixed for e1000 and e1000e, while trying to exclude
            # lro by setting "lro off", the command of ethtool returns error
            if not (
                f_type == "gro"
                and (
                    vm.virtnet[0].nic_model == "e1000e"
                    or vm.virtnet[0].nic_model == "e1000"
                )
            ):
                offload_stat.update(dict.fromkeys(test_matrix[f_type][2], "off"))
            if not ethtool_set(session, offload_stat):
                e_msg = "Failed to set offload status"
                test.log.error(e_msg)
                failed_tests.append(e_msg)

            txt = "Run callback function %s" % callback.__name__
            error_context.context(txt, test.log.info)

            # Some older kernel versions split packets by GSO
            # before tcpdump can capture the big packet, which
            # corrupts our results. Disable check when GSO is
            # enabled.
            if not callback(status="on") and f_type != "gso":
                e_msg = "Callback failed after enabling %s" % f_type
                test.log.error(e_msg)
                failed_tests.append(e_msg)

            if not ethtool_set(session, {f_type: "off"}):
                e_msg = "Failed to disable %s" % f_type
                test.log.error(e_msg)
                failed_tests.append(e_msg)
            txt = "Run callback function %s" % callback.__name__
            error_context.context(txt, test.log.info)
            if not callback(status="off"):
                e_msg = "Callback failed after disabling %s" % f_type
                test.log.error(e_msg)
                failed_tests.append(e_msg)

        if failed_tests:
            test.fail("Failed tests: %s" % failed_tests)

    finally:
        try:
            if session:
                session.close()
        except Exception as detail:
            test.log.error("Fail to close session: '%s'", detail)

        try:
            session = vm.wait_for_serial_login(timeout=login_timeout)
            ethtool_restore_params(session, pretest_status)
        except Exception as detail:
            test.log.warning("Could not restore parameter of" " eth card: '%s'", detail)
