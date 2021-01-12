import os
import json
import logging

from avocado.utils import process
from avocado.utils.network.ports import find_free_port

from virttest import error_context
from virttest.virt_vm import VMMigrateFailedError

from provider import ansible
from provider import message_queuing


@error_context.context_aware
def run(test, params, env):
    """
    Ansible playbook basic test:
    1) Check ansible package exists
    2) Launch the guest
    3) Clone an ansible playbook repo
    4) Generate the ansible-playbook command
    5) Execute the playbook and verify the return status

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    guest_user = params["username"]
    guest_passwd = params["password"]
    step_time = params.get_numeric("step_time", 60)
    ansible_callback_plugin = params.get("ansible_callback_plugin")
    ansible_addl_opts = params.get("ansible_addl_opts", "")
    ansible_ssh_extra_args = params["ansible_ssh_extra_args"]
    ansible_extra_vars = params.get("ansible_extra_vars", "{}")
    playbook_repo = params["playbook_repo"]
    playbook_timeout = params.get_numeric("playbook_timeout")
    playbook_dir = params.get("playbook_dir",
                              os.path.join(test.workdir, "ansible_playbook"))
    toplevel_playbook = os.path.join(playbook_dir, params["toplevel_playbook"])
    # Use this directory to copy some logs back from the guest
    test_harness_log_dir = test.logdir

    # Responsive migration specific parameters
    mq_listen_port = params.get_numeric("mq_listen_port", find_free_port())
    wait_response_timeout = params.get_numeric("wait_response_timeout", 600)

    vms = env.get_all_vms()
    guest_ip_list = []
    for vm in vms:
        vm.verify_alive()
        vm.wait_for_login()
        guest_ip_list.append(vm.get_address())

    logging.info("Cloning %s", playbook_repo)
    process.run("git clone {src} {dst}".format(src=playbook_repo,
                                               dst=playbook_dir), verbose=False)

    error_context.base_context("Generate playbook related options.",
                               logging.info)
    extra_vars = {"ansible_ssh_extra_args": ansible_ssh_extra_args,
                  "ansible_ssh_pass": guest_passwd,
                  "mq_port": mq_listen_port,
                  "test_harness_log_dir": test_harness_log_dir}
    extra_vars.update(json.loads(ansible_extra_vars))

    error_context.context("Execute the ansible playbook.", logging.info)
    playbook_executor = ansible.PlaybookExecutor(
        inventory="{},".format(",".join(guest_ip_list)),
        site_yml=toplevel_playbook,
        remote_user=guest_user,
        extra_vars=json.dumps(extra_vars),
        callback_plugin=ansible_callback_plugin,
        addl_opts=ansible_addl_opts
    )

    mq_publisher = message_queuing.MQPublisher(mq_listen_port)
    try:
        error_context.base_context('Confirm remote subscriber has accessed to '
                                   'activate migrating guests.', logging.info)
        try:
            mq_publisher.confirm_access(wait_response_timeout)
        except message_queuing.MessageNotFoundError as err:
            logging.error(err)
            test.fail("Failed to capture the 'ACCESS' message.")
        logging.info("Already captured the 'ACCESS' message.")

        error_context.context("Migrate guests after subscriber accessed.",
                              logging.info)
        for vm in vms:
            vm.migrate()
    except VMMigrateFailedError:
        error_context.context("Send the 'ALERT' message to notify the remote "
                              "subscriber to stop the test.", logging.info)
        mq_publisher.alert()
        raise
    else:
        error_context.context("Send the 'APPROVE' message to notify the remote "
                              "subscriber to continue the test.", logging.info)
        mq_publisher.approve()
    finally:
        ansible_log = "ansible_playbook.log"
        try:
            playbook_executor.wait_for_completed(playbook_timeout, step_time)
        except ansible.ExecutorTimeoutError as err:
            test.error(str(err))
        else:
            if playbook_executor.get_status() != 0:
                test.fail("Ansible playbook execution failed, please check the "
                          "{} for details.".format(ansible_log))
            logging.info("Ansible playbook execution passed.")
        finally:
            playbook_executor.store_playbook_log(test_harness_log_dir,
                                                 ansible_log)
            playbook_executor.close()
            mq_publisher.close()
