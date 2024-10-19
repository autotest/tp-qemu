from virttest import data_dir, env_process, error_context, qemu_storage


@error_context.context_aware
def run(test, params, env):
    """
    Run an gluster test.
    steps:
    1) create gluster brick if there is no one with good name
    2) create volume on brick
    3) create VM image on disk with specific format
    4) install vm on VM image
    5) boot VM
    6) start fio test on booted VM

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    image_name = params.get("image_name")
    timeout = int(params.get("login_timeout", 360))
    # Workaroud wrong config file order.
    params["image_name_backing_file_snapshot"] = params.get("image_name")
    params["image_format_backing_file_snapshot"] = params.get("image_format")
    params["image_name_snapshot"] = params.get("image_name") + "-snap"

    error_context.context("boot guest over glusterfs", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login(timeout=timeout)
    error_context.context("shutdown VM", test.log.info)
    vm.destroy()
    error_context.context("create snapshot of vm disk", test.log.info)

    snapshot_params = params.object_params("snapshot")

    base_dir = params.get("images_base_dir", data_dir.get_data_dir())
    image = qemu_storage.QemuImg(snapshot_params, base_dir, image_name)
    image.create(snapshot_params)

    env_process.process(
        test,
        snapshot_params,
        env,
        env_process.preprocess_image,
        env_process.preprocess_vm,
    )
