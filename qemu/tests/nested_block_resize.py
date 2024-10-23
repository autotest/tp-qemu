import json
import os
import time

from avocado.utils import process
from virttest import data_dir, error_context, storage

from provider import ansible, message_queuing


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU nested block resize test

    1) Boot the main vm as L1, attach scsi data disk
    2) Pass-through L1 data disk to L2
    3) Run io on the data disk in L2.
    4) Execute block_resize for data disk image on host.
    5) Check L1 status should keep running.
    6) Check L2 status should keep running.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # Check if ansible-playbook program is available
    if not ansible.check_ansible_playbook(params):
        test.cancel("No available ansible-playbook program")

    def _on_exit(obj, msg):
        test.log.info("Receive exit msg:%s", msg)
        obj.set_msg_loop(False)
        status = msg.split(":")[1]
        if status != "0":
            test.fail("Get L2 guest unexpected exit message")

    def _on_resize(obj, msg):
        test.log.info("Receive resize msg:%s", msg)
        data_image_params = params.object_params("stg0")
        data_image_size = params.get_numeric("new_image_size_stg0")
        data_image_filename = storage.get_image_filename(
            data_image_params, data_dir.get_data_dir()
        )
        data_image_dev = vm.get_block({"file": data_image_filename})
        args = (None, data_image_size, data_image_dev)

        vm.monitor.block_resize(*args)
        time.sleep(2)
        vm.verify_status("running")
        guest_cmd_output = session.cmd("lsblk -dn", timeout=60).strip()
        test.log.debug("Guest cmd output: '%s'", guest_cmd_output)
        obj.send_message("status-req")
        test.log.info("Finish handle on_resize")

    def _on_status(obj, msg):
        test.log.info("Receive status msg:%s", msg)
        status = msg.split(":")[1]
        # Notify L2 exit
        obj.send_message("exit")
        if status != "running":
            test.fail("Get unexpected status of L2 guest " + status)
        test.log.info("Finish handle on_status")

    # Error contexts are used to give more info on what was
    # going on when one exception happened executing test code.
    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    # Handle nested ENV
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

    mq_listen_port = params.get_numeric("mq_listen_port", 5000)
    guest_ip_list = [vm.get_address()]

    test.log.info("Cloning %s", playbook_repo)
    process.run(
        "git clone {src} {dst}".format(src=playbook_repo, dst=playbook_dir),
        verbose=False,
    )

    error_context.base_context("Generate playbook related options.", test.log.info)
    extra_vars = {
        "ansible_ssh_pass": guest_passwd,
        "mq_port": mq_listen_port,
        "test_harness_log_dir": test_harness_log_dir,
    }
    extra_vars.update(json.loads(ansible_extra_vars))

    error_context.context("Execute the ansible playbook.", test.log.info)
    playbook_executor = ansible.PlaybookExecutor(
        inventory="{},".format(",".join(guest_ip_list)),
        site_yml=toplevel_playbook,
        remote_user=guest_user,
        extra_vars=json.dumps(extra_vars),
        callback_plugin=ansible_callback_plugin,
        connection_plugin=ansible_connection_plugin,
        addl_opts=ansible_addl_opts,
    )

    # Handle cases

    mq_port = params.get("mq_port", 5000)
    wait_response_timeout = params.get_numeric("wait_response_timeout", 1800)

    mq_publisher = message_queuing.MQPublisher(mq_port, other_options="--broker")

    host = "127.0.0.1"

    test.log.info("host:%s port:%s", host, mq_port)
    client = message_queuing.MQClient(host, mq_port)
    time.sleep(2)

    client.register_msg("resize", _on_resize)
    client.register_msg("status-rsp:", _on_status)
    client.register_msg("exit:", _on_exit)

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
