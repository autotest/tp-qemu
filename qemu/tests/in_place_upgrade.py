import logging

from avocado.utils import process
from virttest import data_dir, error_context, storage

from provider.in_place_upgrade_base import IpuTest

LOG_JOB = logging.getLogger("avocado.test")


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
    check_rhel_ver = params.get("check_rhel_ver")
    pre_rhel_ver = upgrade_test.run_guest_cmd(check_rhel_ver)
    try:
        # set post_release
        pre_release = params.get("pre_release")
        release_chk = params.get("release_check")
        if pre_release not in upgrade_test.run_guest_cmd(release_chk):
            test.cancel("your image is not for rhel %s, please check" % pre_release)
        post_release = params.get("post_release")
        # create an assistant user
        upgrade_test.create_ipuser(test)
        # prepare ipu test env and execute leapp tool
        if not params.get_boolean("com_install"):
            upgrade_test.run_guest_cmd(params.get("com_ins_leapp"))
            upgrade_test.run_guest_cmd(params.get("prepare_env"))
            upgrade_test.run_guest_cmd(params.get("get_answer_files_source"))
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
            if params.get_boolean("com_install"):
                upgrade_test.run_guest_cmd(params.get("com_ins_leapp"))
                upgrade_test.run_guest_cmd(params.get("prepare_env"))
                upgrade_test.run_guest_cmd(params.get("get_answer_files_source"))
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
            if params.get("com_install") == "yes":
                upgrade_test.run_guest_cmd(params.get("com_ins_leapp"))
                upgrade_test.run_guest_cmd(params.get("prepare_env"))
                upgrade_test.run_guest_cmd(params.get("get_answer_files_source"))
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
        upgrade_test.session = vm.wait_for_login(
            timeout=ipu_timeout, username=usr, password=passwd
        )
        # restore settings in the guest
        upgrade_test.post_upgrade_restore(test)
        # post checking
        upgrade_test.post_upgrade_check(test, post_release)
        post_rhel_ver = upgrade_test.run_guest_cmd(check_rhel_ver)
        vm.verify_kernel_crash()
        if params.get("device_cio_free_check_cmd"):
            cio_status = str(
                upgrade_test.session.cmd_status_output(
                    params.get("device_cio_free_check_cmd")
                )
            )
            if "inactive" in cio_status:
                test.fail("device_cio_free is not enabled after upgrading")
    finally:
        vm.graceful_shutdown(timeout=300)
        try:
            image_name = params.objects("images")[0]
            image_params = params.object_params(image_name)
            image_path = params.get("images_base_dir", data_dir.get_data_dir())
            old_name = storage.get_image_filename(image_params, image_path)
            upgraded_name = old_name.replace(pre_rhel_ver, post_rhel_ver)
            process.run(params.get("image_clone_command") % (old_name, upgraded_name))
        except Exception as error:
            test.log.warning("Failed to rename upgraded image:%s", str(error))
