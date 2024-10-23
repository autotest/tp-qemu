from avocado.utils import process
from virttest import error_context, qemu_storage


@error_context.context_aware
def run(test, params, env):
    """
    1) Start VM to make sure it's a bootable system image, shutdown VM
    2) Write a file into the image by guestfish without booting up vm
    3) Read the file and check the content is exactly what we write

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    image_tag = params.get("images").split()[0]
    image_object = qemu_storage.QemuImg(
        params.object_params(image_tag), None, image_tag
    )
    if image_object.image_access:
        test.cancel(
            "Access remote image with tls-creds is "
            "not supported by guestfish, skip the test"
        )

    # Make sure the image holds an OS instance
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    try:
        session = vm.wait_for_login(timeout=params.get_numeric("login_timeout", 360))
        session.close()
    finally:
        vm.destroy()

    msg = params["msg_check"]
    testfile = params["guest_file_name"]
    write_cmd = params["write_cmd"].format(
        fmt=image_object.image_format, uri=image_object.image_filename
    )
    read_cmd = params["read_cmd"].format(
        fmt=image_object.image_format, uri=image_object.image_filename
    )

    test.log.info("Write file '%s'", testfile)
    result = process.run(write_cmd, ignore_status=True, shell=True)
    if result.exit_status != 0:
        test.fail("Failed to write a file, error message: %s" % result.stderr.decode())

    test.log.info("Read file '%s'", testfile)
    result = process.run(read_cmd, ignore_status=True, shell=True)
    if result.exit_status != 0:
        test.fail("Failed to read a file, error message: %s" % result.stderr.decode())
    elif result.stdout.decode().strip() != msg:
        test.fail("Message '%s' mismatched with '%s'" % (msg, result.stdout.decode()))
