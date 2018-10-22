import os
import logging

from virttest import error_context
from virttest import utils_net
from virttest import env_process


@error_context.context_aware
def run(test, params, env):
    """
    Verify guest NIC numbers again whats provided in test config file.

    If the guest NICs info does not match whats in the params at first,
    try to fix these by operating the networking config file.
    1. Boot guest with multi NICs.
    2. Check whether guest NICs info match with params setting.
    3. Create configure file for every NIC interface in guest.
    4. Reboot guest.
    5. Check whether guest NICs info match with params setting.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def check_nics_num(expect_c, session):
        """
        Check whether guest NICs number match with params set in cfg file

        :param expect_c: expected nics no.
        :param session: in which session the guest runs in
        """
        txt = "Check whether guest NICs info match with params setting."
        error_context.context(txt, logging.info)
        nics_list = utils_net.get_linux_ifname(session)
        actual_c = len(nics_list)
        msg = "Expected NICs count is: %d\n" % expect_c
        msg += "Actual NICs count is: %d\n" % actual_c

        if not expect_c == actual_c:
            msg += "Nics count mismatch!\n"
            return (False, msg)
        return (True, msg + 'Nics count match')

    # Get the ethernet cards number from params
    nics_num = int(params.get("nics_num", 8))
    for i in range(nics_num):
        nics = "nic%s" % i
        params["nics"] = ' '.join([params["nics"], nics])
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))

    logging.info("[ %s ] NICs card specified in config file" % nics_num)

    os_type = params.get("os_type", "linux")
    if os_type == "linux":
        # Redirect ifconfig output from guest to log file
        log_file = os.path.join(test.debugdir, "ifconfig")
        ifconfig_output = session.cmd("ifconfig")
        log_file_object = open(log_file, "w")
        log_file_object.write(ifconfig_output)
        log_file_object.close()

        # Pre-judgement for the ethernet interface
        logging.debug(check_nics_num(nics_num, session)[1])
        txt = "Create configure file for every NIC interface in guest."
        error_context.context(txt, logging.info)
        ifname_list = utils_net.get_linux_ifname(session)
        ifcfg_path = "/etc/sysconfig/network-scripts/ifcfg-%s"
        for ifname in ifname_list:
            eth_config_path = ifcfg_path % ifname
            eth_config = "DEVICE=%s\\nBOOTPROTO=dhcp\\nONBOOT=yes" % ifname
            cmd = "echo -e '%s' > %s" % (eth_config, eth_config_path)
            s, o = session.cmd_status_output(cmd)
            if s != 0:
                err_msg = "Failed to create ether config file: %s\nReason is: %s"
                test.error(err_msg % (eth_config_path, o))

        # Reboot and check the configurations.
        session = vm.reboot(session)
        s, msg = check_nics_num(nics_num, session)
        if not s:
            test.fail(msg)
        session.close()

        # NICs matched.
        logging.info(msg)

    # Check all the interfaces in guest get ips
    nic_interface = []
    session_srl = vm.wait_for_serial_login(timeout=int(params.get("login_timeout", 360)))
    for index, nic in enumerate(vm.virtnet):
        logging.info("index %s nic" % index)
        guest_ip = utils_net.get_guest_ip_addr(session_srl, nic.mac, os_type,
                                               ip_version="ipv4")
        if not guest_ip:
            err_log = "vm get interface %s's ip failed." % index
            test.fail(err_log)
        nic_interface.append(guest_ip)
    session_srl.close()
    logging.info("All the [ %s ] NICs get IPs." % nics_num)
