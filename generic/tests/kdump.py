import logging
import os

from autotest.client import utils
from autotest.client.shared import error

from virttest import utils_conn
from virttest import utils_misc
from virttest import utils_net


@error.context_aware
def preprocess_kdump(vm, timeout):
    """
    Backup /etc/kdump.conf file before trigger crash.

    :param timeout: Timeout in seconds
    """
    kdump_cfg_path = vm.params.get("kdump_cfg_path", "/etc/kdump.conf")
    cp_kdumpcf_cmd = "/bin/cp -f %s %s-bk" % (kdump_cfg_path, kdump_cfg_path)
    cp_kdumpcf_cmd = vm.params.get("cp_kdumpcf_cmd", cp_kdumpcf_cmd)

    session = vm.wait_for_login(timeout=timeout)

    logging.info("Backup kdump.conf file.")
    status, output = session.cmd_status_output(cp_kdumpcf_cmd)
    if status != 0:
        logging.error(output)
        raise error.TestError("Fail to backup the kdump.conf")

    session.close()


@error.context_aware
def postprocess_kdump(vm, timeout):
    """
    Restore /etc/kdump.conf file after trigger crash.

    :param timeout: Timeout in seconds
    """
    kdump_cfg_path = vm.params.get("kdump_cfg_path", "/etc/kdump.conf")
    restore_kdumpcf_cmd = "/bin/cp -f %s-bk %s" % (kdump_cfg_path, kdump_cfg_path)
    restore_kdumpcf_cmd = vm.params.get("restore_kdumpcf_cmd", restore_kdumpcf_cmd)

    session = vm.wait_for_login(timeout=timeout)

    logging.info("Restore kdump.conf")
    status, output = session.cmd_status_output(restore_kdumpcf_cmd)
    if status != 0:
        logging.error(output)
        raise error.TestError("Fail to restore the kdump.conf")

    session.close()


@error.context_aware
def kdump_enable(vm, vm_name, crash_kernel_prob_cmd,
                 kernel_param_cmd, kdump_enable_cmd, timeout):
    """
    Check, configure and enable the kdump in guest.

    :param vm_name: vm name
    :param crash_kernel_prob_cmd: check kdume loaded
    :param kernel_param_cmd: the param add into kernel line for kdump
    :param kdump_enable_cmd: enable kdump command
    :param timeout: Timeout in seconds
    """
    kdump_cfg_path = vm.params.get("kdump_cfg_path", "/etc/kdump.conf")
    kdump_config = vm.params.get("kdump_config")
    vmcore_path = vm.params.get("vmcore_path", "/var/crash")
    kdump_method = vm.params.get("kdump_method", "basic")
    kdump_propagate_cmd = vm.params.get("kdump_propagate_cmd")
    kdump_enable_timeout = int(vm.params.get("kdump_enable_timeout", 360))

    error.context("Try to log into guest '%s'." % vm_name, logging.info)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Checking the existence of crash kernel in %s" %
                  vm_name, logging.info)
    try:
        session.cmd(crash_kernel_prob_cmd)
    except Exception:
        error.context("Crash kernel is not loaded. Trying to load it",
                      logging.info)
        session.cmd(kernel_param_cmd)
        session = vm.reboot(session, timeout=timeout)

    if kdump_config:
        if kdump_method == "ssh":
            host_ip = utils_net.get_ip_address_by_interface(vm.params.get('netdst'))
            kdump_config = kdump_config % (host_ip, vmcore_path)

        error.context("Configuring the Core Collector...", logging.info)

        session.cmd("cat /dev/null > %s" % kdump_cfg_path)
        for config_line in kdump_config.split(";"):
            config_cmd = "echo -e '%s' >> %s "
            config_con = config_line.strip()
            session.cmd(config_cmd % (config_con, kdump_cfg_path))

    if kdump_method == "ssh":
        host_pwd = vm.params.get("host_pwd", "redhat")
        guest_pwd = vm.params.get("guest_pwd", "redhat")
        guest_ip = vm.get_address()

        error.context("Setup ssh login without password...", logging.info)
        session.cmd("rm -rf /root/.ssh/*")

        ssh_connection = utils_conn.SSHConnection(server_ip=host_ip,
                                                  server_pwd=host_pwd,
                                                  client_ip=guest_ip,
                                                  client_pwd=guest_pwd)
        try:
            ssh_connection.conn_check()
        except utils_conn.ConnectionError:
            ssh_connection.conn_setup()
            ssh_connection.conn_check()

        logging.info("Trying to propagate with command '%s'" %
                     kdump_propagate_cmd)
        session.cmd(kdump_propagate_cmd, timeout=120)

    error.context("Enabling kdump service...", logging.info)
    # the initrd may be rebuilt here so we need to wait a little more
    session.cmd(kdump_enable_cmd, timeout=kdump_enable_timeout)

    return session


@error.context_aware
def crash_test(vm, vcpu, crash_cmd, timeout):
    """
    Trigger a crash dump through sysrq-trigger

    :param vcpu: vcpu which is used to trigger a crash
    :param crash_cmd: crash_cmd which is triggered crash command
    :param timeout: Timeout in seconds
    """
    vmcore_path = vm.params.get("vmcore_path", "/var/crash")
    kdump_method = vm.params.get("kdump_method", "basic")
    vmcore_rm_cmd = vm.params.get("vmcore_rm_cmd", "rm -rf %s/*")
    vmcore_rm_cmd = vmcore_rm_cmd % vmcore_path
    kdump_restart_cmd = vm.params.get("kdump_restart_cmd",
                                      "service kdump restart")
    kdump_status_cmd = vm.params.get("kdump_status_cmd",
                                     "systemctl status kdump.service")

    session = vm.wait_for_login(timeout=timeout)

    logging.info("Delete the vmcore file.")
    if kdump_method == "ssh":
        utils.run(vmcore_rm_cmd)
    else:
        session.cmd_output(vmcore_rm_cmd)

    session.cmd(kdump_restart_cmd, timeout=120)

    debug_msg = "Kdump service status before our testing:\n"
    debug_msg += session.cmd(kdump_status_cmd)

    logging.debug(debug_msg)

    try:
        if crash_cmd == "nmi":
            logging.info("Triggering crash with 'nmi' interrupt")
            session.cmd("echo 1 > /proc/sys/kernel/unknown_nmi_panic")
            vm.monitor.nmi()
        else:
            logging.info("Triggering crash on vcpu %d ...", vcpu)
            session.sendline("taskset -c %d %s" % (vcpu, crash_cmd))
    except Exception:
        postprocess_kdump(vm, timeout)


@error.context_aware
def check_vmcore(vm, session, timeout):
    """
    Check the vmcore file after triggering a crash

    :param session: A shell session object or None.
    :param timeout: Timeout in seconds
    """
    vmcore_path = vm.params.get("vmcore_path", "/var/crash")
    vmcore_chk_cmd = vm.params.get("vmcore_chk_cmd", "ls -R %s | grep vmcore")
    vmcore_chk_cmd = vmcore_chk_cmd % vmcore_path

    if not utils_misc.wait_for(lambda: not session.is_responsive(), 240, 0, 1):
        raise error.TestFail("Could not trigger crash.")

    error.context("Waiting for kernel crash dump to complete", logging.info)
    session = vm.wait_for_login(timeout=timeout)

    error.context("Probing vmcore file...", logging.info)
    try:
        if vm.params.get("kdump_method") == "ssh":
            logging.info("Checking vmcore file on host")
            utils.run(vmcore_chk_cmd)
        else:
            logging.info("Checking vmcore file on guest")
            session.cmd(vmcore_chk_cmd)
    except Exception:
        postprocess_kdump(vm, timeout)
        raise error.TestFail("Could not found vmcore file.")

    logging.info("Found vmcore.")


@error.context_aware
def run(test, params, env):
    """
    KVM kdump test:
    1) Log into the guest(s)
    2) Check, configure and enable the kdump
    3) Trigger a crash by 'sysrq-trigger' and check the vmcore for each vcpu,
       or only trigger one crash with 'nmi' interrupt and check vmcore.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    timeout = float(params.get("login_timeout", 240))
    crash_timeout = float(params.get("crash_timeout", 360))
    def_kernel_param_cmd = ("grubby --update-kernel=`grubby --default-kernel`"
                            " --args=crashkernel=128M@16M")
    kernel_param_cmd = params.get("kernel_param_cmd", def_kernel_param_cmd)
    def_kdump_enable_cmd = "chkconfig kdump on && service kdump restart"
    kdump_enable_cmd = params.get("kdump_enable_cmd", def_kdump_enable_cmd)
    def_crash_kernel_prob_cmd = "grep -q 1 /sys/kernel/kexec_crash_loaded"
    crash_kernel_prob_cmd = params.get("crash_kernel_prob_cmd",
                                       def_crash_kernel_prob_cmd)
    kdump_cfg_path = params.get("kdump_cfg_path", "/etc/kdump.conf")

    vms = params.get("vms", "vm1 vm2").split()
    vm_list = []
    session_list = []

    try:
        for vm_name in vms:
            vm = env.get_vm(vm_name)
            vm.verify_alive()
            vm_list.append(vm)

            preprocess_kdump(vm, timeout)
            vm.copy_files_from(kdump_cfg_path,
                               os.path.join(test.debugdir,
                                            "kdump.conf-%s" % vm_name))

            session = kdump_enable(vm, vm_name, crash_kernel_prob_cmd,
                                   kernel_param_cmd, kdump_enable_cmd, timeout)

            session_list.append(session)

        for vm in vm_list:
            error.context("Kdump Testing, force the Linux kernel to crash",
                          logging.info)
            crash_cmd = params.get("crash_cmd", "echo c > /proc/sysrq-trigger")

            session = vm.wait_for_login(timeout=timeout)
            vm.copy_files_from(kdump_cfg_path,
                               os.path.join(test.debugdir,
                                            "kdump.conf-%s-test" % vm.name))
            if crash_cmd == "nmi":
                crash_test(vm, None, crash_cmd, timeout)
            else:
                # trigger crash for each vcpu
                nvcpu = int(params.get("smp", 1))
                for i in range(nvcpu):
                    crash_test(vm, i, crash_cmd, timeout)

        for i in range(len(vm_list)):
            error.context("Check the vmcore file after triggering a crash",
                          logging.info)
            check_vmcore(vm_list[i], session_list[i], crash_timeout)
    finally:
        for s in session_list:
            s.close()
        for vm in vm_list:
            postprocess_kdump(vm, timeout)
            vm.destroy()
