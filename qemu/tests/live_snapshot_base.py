from avocado.utils import crypto, process
from virttest import data_dir, error_context, storage, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_base test:
    1). Boot up guest
    2). Create a file on host and record md5
    3). Copy the file to guest
    3). Create live snapshot
    4). Copy the file from guest,then check md5

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 3600))
    session = vm.wait_for_login(timeout=timeout)

    dd_timeout = params.get("dd_timeoout", 600)
    copy_timeout = params.get("copy_timeoout", 600)
    base_file = storage.get_image_filename(params, data_dir.get_data_dir())
    device = vm.get_block({"file": base_file})
    snapshot_file = "images/%s" % params.get("snapshot_file")
    snapshot_file = utils_misc.get_path(data_dir.get_data_dir(), snapshot_file)
    snapshot_format = params.get("snapshot_format", "qcow2")
    tmp_name = utils_misc.generate_random_string(5)
    src = dst = "/tmp/%s" % tmp_name
    if params.get("os_type") != "linux":
        dst = "c:\\users\\public\\%s" % tmp_name

    try:
        error_context.context("create file on host, copy it to guest", test.log.info)
        cmd = params.get("dd_cmd") % src
        process.system(cmd, timeout=dd_timeout, shell=True)
        md5 = crypto.hash_file(src, algorithm="md5")
        vm.copy_files_to(src, dst, timeout=copy_timeout)
        process.system("rm -f %s" % src)
        error_context.context("create live snapshot", test.log.info)
        if vm.live_snapshot(base_file, snapshot_file, snapshot_format) != device:
            test.fail("Fail to create snapshot")
        backing_file = vm.monitor.get_backingfile(device)
        if backing_file != base_file:
            test.log.error("backing file: %s, base file: %s", backing_file, base_file)
            test.fail("Got incorrect backing file")
        error_context.context(
            "copy file to host, check content not changed", test.log.info
        )
        vm.copy_files_from(dst, src, timeout=copy_timeout)
        if md5 and (md5 != crypto.hash_file(src, algorithm="md5")):
            test.fail("diff md5 before/after create snapshot")
        session.cmd(params.get("alive_check_cmd", "dir"))
    finally:
        if session:
            session.close()
        process.system("rm -f %s %s" % (snapshot_file, src))
