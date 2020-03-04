import logging
import os

from avocado.utils import process

from virttest import data_dir
from virttest import error_context
from virttest import utils_disk
from virttest import utils_misc
from virttest.remote import scp_to_remote

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs by sharing the data between host and guest.
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofsd daemons on the host.
        3. Boot a guest on the host with virtiofs options.
        4. Log into guest then mount the virtiofs targets.
        5. Generate files or run stress on the mount points inside guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    cmd_dd = params.get('cmd_dd')
    cmd_md5 = params.get('cmd_md5')

    cmd_pjdfstest = params.get('cmd_pjdfstest')
    cmd_unpack = params.get('cmd_unpack')
    cmd_yum_deps = params.get('cmd_yum_deps')
    cmd_autoreconf = params.get('cmd_autoreconf')
    cmd_configure = params.get('cmd_configure')
    cmd_make = params.get('cmd_make')
    pjdfstest_pkg = params.get('pjdfstest_pkg')

    fio_options = params.get('fio_options')
    io_timeout = params.get_numeric('io_timeout')

    username = params.get('username')
    password = params.get('password')
    port = params.get('file_transfer_port')

    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()
    host_addr = vm.get_address()

    for fs in params.objects("filesystems"):
        fs_params = params.object_params(fs)
        fs_target = fs_params.get("fs_target")
        fs_dest = fs_params.get("fs_dest")

        fs_source = fs_params.get("fs_source_dir")
        base_dir = fs_params.get("fs_source_base_dir", data_dir.get_data_dir())
        if not os.path.isabs(fs_source):
            fs_source = os.path.join(base_dir, fs_source)
        guest_data = os.path.join(fs_dest, 'fs_test')
        host_data = os.path.join(fs_source, 'fs_test')

        error_context.context("Create a destination directory %s "
                              "inside guest." % fs_dest, logging.info)
        utils_misc.make_dirs(fs_dest, session)

        error_context.context("Mount virtiofs target %s to %s inside guest."
                              % (fs_target, fs_dest), logging.info)
        utils_disk.mount(fs_target, fs_dest, 'virtiofs', session=session)

        try:
            if cmd_dd:
                logging.info("Creating file under %s inside guest." % fs_dest)
                session.cmd(cmd_dd % guest_data, io_timeout)
                logging.info("Compare the md5 between guest and host.")
                md5_guest = session.cmd(cmd_md5 % guest_data,
                                        io_timeout).strip().split()[0]
                logging.info(md5_guest)
                md5_host = process.run(cmd_md5 % host_data,
                                       io_timeout).stdout_text.strip().split()[0]
                if md5_guest != md5_host:
                    test.fail('The md5 value of host is not same to guest.')

            if fio_options:
                error_context.context("Run fio on %s." % fs_dest, logging.info)
                fio = generate_instance(params, vm, 'fio')
                try:
                    fio.run(fio_options % guest_data, io_timeout)
                finally:
                    fio.clean()
                vm.verify_dmesg()

            if cmd_pjdfstest:
                error_context.context("Run pjdfstest on %s." % fs_dest, logging.info)
                host_path = os.path.join(data_dir.get_deps_dir('pjdfstest'), pjdfstest_pkg)
                scp_to_remote(host_addr, port, username, password, host_path, fs_dest)
                session.cmd(cmd_unpack.format(fs_dest), 180)
                session.cmd(cmd_yum_deps, 180)
                session.cmd(cmd_autoreconf % fs_dest, 180)
                session.cmd(cmd_configure.format(fs_dest), 180)
                session.cmd(cmd_make % fs_dest, io_timeout)
                session.cmd(cmd_pjdfstest % fs_dest, io_timeout)
        finally:
            utils_disk.umount(fs_target, fs_dest, 'virtiofs', session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
