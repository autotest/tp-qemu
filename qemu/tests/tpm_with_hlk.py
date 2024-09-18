from virttest import env_process

from provider.win_hlk_suite import (
    HLKServer,
    download_hlk_server_image,
    install_hlk_client,
)


def run(test, params, env):
    """
    Test TPM device by Windows Hardware Lab Kit(HLK).
    Steps:
        1. Boot HLK server in windows guest.
        2. Boot another windows guest with tpm-crb device as HLK client.
        3. Installation HLK client inside guest.
        4. Setup environment then run corresponding test cases inside HLK
           server guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    server_img = download_hlk_server_image(params, params.get("hlk_server_image_uri"))
    vm_name_hlk_server = params.get("vm_name_hlk_server")

    params["images_%s" % vm_name_hlk_server] = "image0"
    params["image_name_image0_%s" % vm_name_hlk_server] = server_img["image_name"]
    params["image_size_image0_%s" % vm_name_hlk_server] = server_img["image_size"]
    params["image_format_image0_%s" % vm_name_hlk_server] = server_img["image_format"]

    params["start_vm"] = "yes"
    params["not_preprocess"] = "no"
    env_process.preprocess(test, params, env)

    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()
        if vm.name == vm_name_hlk_server:
            vm_server = vm
        else:
            vm_client = vm

    install_hlk_client(vm_client, vm_server)  # pylint: disable=E0606

    pool_name = params.get("hlk_pool_name")
    project_name = params.get("hlk_project_name")
    target_name = params.get("hlk_target_name")
    tests_name = [name for name in params.get("hlk_target_tests_name").split(";")]
    hlk_server = HLKServer(test, vm_server)
    hlk_server.simple_run_test(
        pool_name, project_name, target_name, tests_name, timeout=24000, step=600
    )
    hlk_server.close()
