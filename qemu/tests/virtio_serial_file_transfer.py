from virttest import utils_test


def run(test, params, env):
    """
    Test virtio serial guest file transfer.

    Steps:
    1) Boot up a VM with virtio serial device.
    2) Create a large file in guest or host.
    3) Copy this file between guest and host through virtio serial.
    4) Check if file transfers ended good by md5 (optional).

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    port_names = params.get("file_transfer_serial_port", "").split()
    file_sender = params.get("file_sender", "guest")
    md5_check = params.get("md5_check", "yes") == "yes"

    utils_test.run_virtio_serial_file_transfer(test, params, env,
                                               port_names=port_names,
                                               sender=file_sender,
                                               md5_check=md5_check)
