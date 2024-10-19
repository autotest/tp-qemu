import json
import os

from avocado.utils import process
from virttest import env_process, error_context

from provider import ansible


@error_context.context_aware
def run(test, params, env):
    """
    Ansible playbook basic test:
    1) Check ansible-playbook exists and try to install it if not exists
    2) Launch the guest if ansible-playbook program exists
    3) Clone an ansible playbook repo
    4) Generate the ansible-playbook command
    5) Execute the playbook and verify the return status

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    # check ansible-playbook program
    if not ansible.check_ansible_playbook(params):
        test.cancel("No available ansible-playbook program")

    guest_user = params["username"]
    guest_passwd = params["password"]
    step_time = params.get_numeric("step_time", 60)
    ansible_callback_plugin = params.get("ansible_callback_plugin")
    ansible_connection_plugin = params.get("ansible_connection_plugin")
    ansible_addl_opts = params.get("ansible_addl_opts", "")
    ansible_extra_vars = params.get("ansible_extra_vars", "{}")
    custom_extra_vars = params.objects("custom_extra_vars")
    playbook_repo = params["playbook_repo"]
    playbook_timeout = params.get_numeric("playbook_timeout")
    playbook_dir = params.get(
        "playbook_dir", os.path.join(test.workdir, "ansible_playbook")
    )
    toplevel_playbook = os.path.join(playbook_dir, params["toplevel_playbook"])
    # Use this directory to copy some logs back from the guest
    test_harness_log_dir = test.logdir

    params["start_vm"] = "yes"
    env_process.preprocess(test, params, env)
    vms = env.get_all_vms()
    guest_ip_list = []
    for vm in vms:
        vm.verify_alive()
        vm.wait_for_login()
        guest_ip_list.append(vm.get_address())

    test.log.info("Cloning %s", playbook_repo)
    process.run(
        "git clone {src} {dst}".format(src=playbook_repo, dst=playbook_dir),
        verbose=False,
    )

    error_context.base_context("Generate playbook related options.", test.log.info)
    extra_vars = {
        "ansible_ssh_pass": guest_passwd,
        "test_harness_log_dir": test_harness_log_dir,
    }
    extra_vars.update(json.loads(ansible_extra_vars))
    custom_params = params.object_params("extra_vars")
    for cev in custom_extra_vars:
        extra_vars[cev] = custom_params[cev]

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

    ansible_log = "ansible_playbook.log"
    try:
        playbook_executor.wait_for_completed(playbook_timeout, step_time)
    except ansible.ExecutorTimeoutError as err:
        test.error(str(err))
    else:
        if playbook_executor.get_status() != 0:
            test.fail(
                "Ansible playbook execution failed, please check the {} "
                "for details.".format(ansible_log)
            )
        test.log.info("Ansible playbook execution passed.")
    finally:
        playbook_executor.store_playbook_log(test_harness_log_dir, ansible_log)
        playbook_executor.close()
