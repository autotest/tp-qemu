import os

from virttest import data_dir, error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check the Hyper-V type

    1) boot the guest with all flags
    2) check Hyper-V type in guest

    param test: the test object
    param params: the test params
    param env: the test env object
    """
    timeout = params.get_numeric("timeout", 360)
    virt_what_remove_cmd = params["virt_what_remove_cmd"]
    virt_what_chk_cmd = params["virt_what_chk_cmd"]
    virt_what_pkg = params["virt_what_pkg"]
    virt_what_guest_dir = params["virt_what_guest_dir"]
    virt_what_install_cmd = params["virt_what_install_cmd"]
    clean_virt_what_pkg_cmd = params["clean_virt_what_pkg_cmd"]
    error_context.context("Boot the guest with all flags", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    # use virt-what-1.18-6.el8.x86_64 for testing
    # as lastest virt-what package with regression issue
    # can only show one signature.
    status = session.cmd_status(virt_what_chk_cmd)
    if status == 0:
        status = session.cmd_status(virt_what_remove_cmd)
        if status:
            test.error("Fail to uninstall existing virt-what")
    test.log.info("Copy target virt-what pkg to guest")
    virt_what_pkg = os.path.join(data_dir.get_deps_dir("virt_what"), virt_what_pkg)
    try:
        vm.copy_files_to(virt_what_pkg, virt_what_guest_dir)
        status = session.cmd_status(virt_what_install_cmd)
        if status:
            test.error("Fail to install target virt-what")
        hv_type = session.cmd("virt-what")
        test.log.debug("Guest 'virt-what': %s", hv_type)
        if "kvm" not in hv_type or "hyperv" not in hv_type:
            test.fail("Hyiper-V type mismatch, should be both KVM & hyperv")
    finally:
        test.log.info("Clean virt-what pkg")
        session.cmd(clean_virt_what_pkg_cmd, ignore_all_errors=True)
