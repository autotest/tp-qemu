from avocado.utils import process
from virttest import env_process, error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Vhost zero copy test
    1) Enable/Disable vhost_net zero copy in host
    1) Boot the main vm.
    3) Run the ping test, check guest nic works.
    4) check vm is alive have no crash

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def zerocp_enable_status():
        """
        Check whether host have enabled zero copy, if enabled return True,
        else return False.
        """
        def_para_path = "/sys/module/vhost_net/parameters/experimental_zcopytx"
        para_path = params.get("zcp_set_path", def_para_path)
        cmd_status = process.system("grep 1 %s" % para_path, ignore_status=True)
        if cmd_status:
            return False
        else:
            return True

    def enable_zerocopytx_in_host(test, enable=True):
        """
        Enable or disable vhost_net zero copy in host
        """
        cmd = "modprobe -rf vhost_net; "
        if enable:
            cmd += "modprobe vhost-net experimental_zcopytx=1"
        else:
            cmd += "modprobe vhost-net experimental_zcopytx=0"
        if process.system(cmd, shell=True) or enable != zerocp_enable_status():
            test.cancel("Set vhost_net zcopytx failed")

    error_context.context("Set host vhost_net experimental_zcopytx", test.log.info)
    if params.get("enable_zerocp", "yes") == "yes":
        enable_zerocopytx_in_host(test)
    else:
        enable_zerocopytx_in_host(test, False)

    error_context.context("Boot vm with 'vhost=on'", test.log.info)
    if params.get("nettype") == "user":
        test.cancel("Unable start test with user networking, please " "change nettype.")
    params["vhost"] = "vhost=on"
    params["start_vm"] = "yes"
    login_timeout = int(params.get("login_timeout", 360))
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=login_timeout)
    guest_ip = vm.get_address()

    error_context.context("Check guest nic is works by ping", test.log.info)
    status, output = utils_test.ping(guest_ip, count=10, timeout=20)
    if status:
        err_msg = "Run ping %s failed, after set zero copy" % guest_ip
        test.error(err_msg)
    elif utils_test.get_loss_ratio(output) == 100:
        err_msg = "All packets lost during ping guest %s." % guest_ip
        test.fail(err_msg)

    # in vm.verify_alive will check whether have userspace or kernel crash
    error_context.context("Check guest is alive and have no crash", test.log.info)
    vm.verify_alive()
