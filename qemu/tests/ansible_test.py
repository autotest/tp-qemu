import os
import json
import logging

from avocado.utils import process

from virttest import error_context

from provider.ansible import PlaybookExecutor


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
                  "test_harness_log_dir": test_harness_log_dir}
    extra_vars.update(json.loads(ansible_extra_vars))

    error_context.context("Execute the ansible playbook.", logging.info)
    playbook_executor = PlaybookExecutor(
        inventory="{},".format(",".join(guest_ip_list)),
        site_yml=toplevel_playbook,
        remote_user=guest_user,
        extra_vars=json.dumps(extra_vars),
        callback_plugin=ansible_callback_plugin,
        addl_opts=ansible_addl_opts
    )

    playbook_executor.wait_for_completed(playbook_timeout, step_time)

    ansible_log = "ansible_playbook.log"
    playbook_executor.store_playbook_log(test_harness_log_dir, ansible_log)
    if playbook_executor.get_status() != 0:
        test.fail("Ansible playbook execution failed, please check the {} "
                  "for details.".format(ansible_log))
    logging.info("Ansible playbook execution passed.")
    playbook_executor.close()
