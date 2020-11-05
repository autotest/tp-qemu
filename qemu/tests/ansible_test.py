import os
import json
import logging

from avocado.utils import process
from avocado.utils import software_manager

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Ansible playbook basic test:
    1) Check ansible package exists
    2) Launch the guest
    3) Clone an ansible playbook repo
    4) Generate the ansible-playbook command
    5) Execute the playbook and verify the return status

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    sm = software_manager.SoftwareManager()
    if not (sm.check_installed("ansible") or sm.install("ansible")):
        test.cancel("ansible package install failed")

    guest_user = params["username"]
    guest_passwd = params["password"]
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

    guest_ip_list = []
    for vm in env.get_all_vms():
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

    ansible_cmd_options = ["ansible-playbook",
                           "-u {}".format(guest_user),
                           "-i {},".format(",".join(guest_ip_list)),
                           "-e '{}'".format(json.dumps(extra_vars)),
                           ansible_addl_opts,
                           toplevel_playbook]
    ansible_cmd = r" ".join(ansible_cmd_options)

    error_context.context("Execute the ansible playbook.", logging.info)
    env_vars = ({"ANSIBLE_STDOUT_CALLBACK": ansible_callback_plugin}
                if ansible_callback_plugin else None)
    logging.info("Command of ansible playbook: '%s'", ansible_cmd)
    play_s, play_o = process.getstatusoutput(ansible_cmd,
                                             timeout=playbook_timeout,
                                             shell=False, env=env_vars)
    ansible_log = "ansible_playbook.log"
    with open(os.path.join(test_harness_log_dir, ansible_log), "w") as log_file:
        log_file.write(play_o)
        log_file.flush()

    if play_s != 0:
        test.fail("Ansible playbook execution failed, please check the {} "
                  "for details.".format(ansible_log))
    logging.info("Ansible playbook execution passed.")
