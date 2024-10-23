import json
import os
import time

from avocado.utils import path, process
from virttest import error_context, utils_misc

from provider import ansible, message_queuing
from qemu.tests import vsock_test


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU vsock concatenate sockets test in nested guests

    1) Boot L1 guest with vsock devices
    2) Send message from host to L1 guest
    3) Start L2 guest on L1
    4) Create a file and send it to L1

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _on_exit(obj, msg):
        obj.set_msg_loop(False)

    def _send_file_from_host_to_l1(obj, msg):
        test.log.info("Received message: %s", msg)
        test.log.info("vm.address: %s", vm.get_address(timeout=120))

        vsock_port = params.get_numeric("vsock_port", 2345)
        dd_cmd = "dd if=/dev/urandom of=%s count=10240 bs=1024" % tmp_file
        process.system(dd_cmd, shell=True)
        md5_origin = process.system_output("md5sum %s" % tmp_file).split()[0]

        cmd_transfer = None
        if vsock_test_tool == "ncat":
            tool_bin = path.find_command("ncat")
            cmd_transfer = "%s --vsock --send-only -l %s < %s &" % (
                tool_bin,
                vsock_port,
                tmp_file,
            )
        if vsock_test_tool == "nc_vsock":
            tool_bin = vsock_test.compile_nc_vsock(test, vm, session)
            cmd_transfer = "%s -l %s < %s &" % (tool_bin, vsock_port, tmp_file)
        if cmd_transfer is None:
            raise ValueError(f"unsupported test tool: {vsock_test_tool}")

        test.log.info("cmd_transfer: %s", cmd_transfer)
        process.run(cmd_transfer, ignore_bg_processes=True, shell=True)

        md5_origin = "md5_origin:" + md5_origin.decode()
        obj.send_message(md5_origin)

    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    vsock_test_tool = params["vsock_test_tool"]
    tmp_file = "/var/tmp/vsock_file_%s" % utils_misc.generate_random_string(6)

    disable_firewall = params.get("disable_firewall")
    session.cmd(disable_firewall, ignore_all_errors=True)

    # Setup nested enviroment
    guest_user = params["username"]
    guest_passwd = params["password"]
    step_time = params.get_numeric("step_time", 60)
    ansible_callback_plugin = params.get("ansible_callback_plugin")
    ansible_connection_plugin = params.get("ansible_connection_plugin")
    ansible_addl_opts = params.get("ansible_addl_opts", "")
    ansible_extra_vars = params.get("ansible_extra_vars", "{}")
    playbook_repo = params["playbook_repo"]
    playbook_timeout = params.get_numeric("playbook_timeout")
    playbook_dir = params.get(
        "playbook_dir", os.path.join(test.workdir, "ansible_playbook")
    )
    toplevel_playbook = os.path.join(playbook_dir, params["toplevel_playbook"])
    # Use this directory to copy some logs back from the guest
    test_harness_log_dir = test.logdir

    mq_port = params.get_numeric("mq_listen_port", 2000)
    guest_ip = vm.get_address()

    test.log.info("Cloning %s", playbook_repo)
    process.run(
        "git clone {src} {dst}".format(src=playbook_repo, dst=playbook_dir),
        verbose=False,
    )

    error_context.base_context("Generate playbook related options.", test.log.info)
    extra_vars = {
        "ansible_ssh_pass": guest_passwd,
        "mq_port": mq_port,
        "test_harness_log_dir": test_harness_log_dir,
    }
    extra_vars.update(json.loads(ansible_extra_vars))

    error_context.context("Execute the ansible playbook.", test.log.info)
    playbook_executor = ansible.PlaybookExecutor(
        inventory=guest_ip + ",",
        site_yml=toplevel_playbook,
        remote_user=guest_user,
        extra_vars=json.dumps(extra_vars),
        callback_plugin=ansible_callback_plugin,
        connection_plugin=ansible_connection_plugin,
        addl_opts=ansible_addl_opts,
    )

    # Handle test cases
    wait_response_timeout = params.get_numeric("wait_response_timeout", 600)

    mq_publisher = message_queuing.MQPublisher(mq_port, other_options="--broker")

    host = "127.0.0.1"

    test.log.info("host:%s port:%s", host, mq_port)
    client = message_queuing.MQClient(host, mq_port)
    time.sleep(2)

    test.log.info("vm.address: %s", vm.get_address())
    client.register_msg("L1_up", _send_file_from_host_to_l1)
    client.register_msg("exit", _on_exit)

    try:
        client.msg_loop(timeout=wait_response_timeout)
        test.log.debug("Finish msg_loop")
    finally:
        ansible_log = "ansible_playbook.log"
        try:
            playbook_executor.wait_for_completed(playbook_timeout, step_time)
        except ansible.ExecutorTimeoutError as err:
            test.error(str(err))
        else:
            if playbook_executor.get_status() != 0:
                test.fail(
                    "Ansible playbook execution failed, please check the "
                    "{} for details.".format(ansible_log)
                )
            test.log.info("Ansible playbook execution passed.")
        finally:
            playbook_executor.store_playbook_log(test_harness_log_dir, ansible_log)
            playbook_executor.close()
            client.close()
            mq_publisher.close()
            test.log.debug("MQ closed")
            process.system("rm -f %s" % tmp_file)
