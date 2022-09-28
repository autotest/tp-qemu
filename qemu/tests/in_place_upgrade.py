import logging


from virttest import error_context
from provider.in_place_upgrade_base import IpuTest


LOG_JOB = logging.getLogger('avocado.test')


@error_context.context_aware
def run(test, params, env):
    """
    Run in place upgrade cases:
    a) without RHSM
    1.configure vm
    2.install leapp tool
    3.download new rhel content repo
    4.pre_upgrade test in the vm
    5.upgrade test in the vm
    6.check if it's target system

    b) with rhsm
    1.configure vm
    2.install leapp tool
    3.subscribe vm
    4.pre_upgrade test in the vm
    5.upgrade test in the vm
    6.check if it's target system

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    upgrade_test = IpuTest(test, params)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    upgrade_test.session = vm.wait_for_login(timeout=login_timeout)
    try:
        # set post_release
        pre_release = params.get("pre_release")
        release_chk = params.get("release_check")
        if pre_release not in upgrade_test.run_guest_cmd(release_chk):
            test.cancel("your image is not for rhel 8 product, please check")
        post_release = params.get("post_release")
        # create an assistant user
        upgrade_test.create_ipuser(test)
        # prepare ipu test env and execute leapp tool
        upgrade_test.run_guest_cmd(params.get("repo_leapp"))
        upgrade_test.run_guest_cmd(params.get("ins_leapp_cmd"))
        upgrade_test.run_guest_cmd(params.get("prepare_env"))
        upgrade_test.run_guest_cmd(params.get("get_answer_files_source"))
        upgrade_test.run_guest_cmd(params.get("get_answer_files"))
        vm_arch = params.get("vm_arch_name")
        enable_content = params.get("enable_content")
        params["enable_content"] = enable_content.format(vm_arch, vm_arch)
        if params.get("rhsm_type") == "no_rhsm":
            # update vm by repos
            # please specify the old_custom_internal_repo in the cfg in advance
            # this parameter should contain the repo files,
            # by which you can upgrade old system to the newer version
            # before you really do in place upgade
            old_custom_repo = params.get("old_custom_internal_repo")
            upgrade_test.yum_update_no_rhsm(test, old_custom_repo)
            upgrade_test.session = vm.reboot(upgrade_test.session)
            # please specify the new_internal_repo in the cfg in advance
            # this parameter should contain your upgraded system's repo files
            upgrade_test.run_guest_cmd(params.get("new_rhel_content"))
            upgrade_test.pre_upgrade_whitelist(test)
            upgrade_test.run_guest_cmd(params.get("pre_upgrade_no_rhsm"))
            # process upgrade
            upgrade_test.upgrade_process(params.get("process_upgrade_no_rhsm"))
        elif params.get("rhsm_type") == "rhsm":
            upgrade_test.rhsm(test)
            upgrade_test.session = vm.reboot(upgrade_test.session)
            upgrade_test.pre_upgrade_whitelist(test)
            upgrade_test.run_guest_cmd(params.get("pre_upgrade_rhsm"))
            # process upgrade
            upgrade_test.upgrade_process(params.get("process_upgrade_rhsm"))
        # after run upgrade, reboot the guest after finish preupgrade
        upgrade_test.session.sendline(params.get("reboot_cmd"))
        # login in new rhel9 vm by assitant user
        ipu_timeout = int(params.get("ipu_after_timeout"))
        usr = params.get("user_assistant")
        passwd = params.get("user_assistant_pw")
        upgrade_test.session = vm.wait_for_login(timeout=ipu_timeout,
                                                 username=usr, password=passwd)
        # restore settings in the guest
        upgrade_test.post_upgrade_restore(test)
        # post checking
        upgrade_test.post_upgrade_check(test, post_release)
        vm.verify_kernel_crash()
    finally:
        if upgrade_test.session:
            upgrade_test.session.close()
        vm.destroy()
