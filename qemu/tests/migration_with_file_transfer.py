import logging
import os

from avocado.utils import crypto
from avocado.utils import process

from virttest import error_context
from virttest import utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM migration test:
    1) Get a live VM and clone it.
    2) Verify that the source VM supports migration.  If it does, proceed with
            the test.
    3) Transfer file from host to guest.
    4) Repeatedly migrate VM and wait until transfer's finished.
    5) Transfer file from guest back to host.
    6) Repeatedly migrate VM and wait until transfer's finished.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2

    host_path = "/tmp/file-%s" % utils_misc.generate_random_string(6)
    host_path_returned = "%s-returned" % host_path
    guest_path = params.get("guest_path", "/tmp/file")
    file_size = params.get("file_size", "500")
    transfer_timeout = int(params.get("transfer_timeout", "240"))
    migrate_between_vhost_novhost = params.get("migrate_between_vhost_novhost")

    try:
        process.run("dd if=/dev/urandom of=%s bs=1M count=%s"
                    % (host_path, file_size))

        def run_and_migrate(bg):
            bg.start()
            try:
                while bg.isAlive():
                    logging.info("File transfer not ended, starting a round of "
                                 "migration...")
                    if migrate_between_vhost_novhost == "yes":
                        vhost_status = vm.params.get("vhost")
                        if vhost_status == "vhost=on":
                            vm.params["vhost"] = "vhost=off"
                        elif vhost_status == "vhost=off":
                            vm.params["vhost"] = "vhost=on"
                    vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay,
                               env=env)
            except Exception:
                # If something bad happened in the main thread, ignore
                # exceptions raised in the background thread
                bg.join(suppress_exception=True)
                raise
            else:
                bg.join()

        error_context.context("transferring file to guest while migrating",
                              logging.info)
        bg = utils_misc.InterruptedThread(
            vm.copy_files_to,
            (host_path, guest_path),
            dict(verbose=True, timeout=transfer_timeout))
        run_and_migrate(bg)

        error_context.context("transferring file back to host while migrating",
                              logging.info)
        bg = utils_misc.InterruptedThread(
            vm.copy_files_from,
            (guest_path, host_path_returned),
            dict(verbose=True, timeout=transfer_timeout))
        run_and_migrate(bg)

        # Make sure the returned file is identical to the original one
        error_context.context("comparing hashes", logging.info)
        orig_hash = crypto.hash_file(host_path)
        returned_hash = crypto.hash_file(host_path_returned)
        if orig_hash != returned_hash:
            test.fail("Returned file hash (%s) differs from "
                      "original one (%s)" % (returned_hash, orig_hash))
        error_context.context()

    finally:
        session.close()
        if os.path.isfile(host_path):
            os.remove(host_path)
        if os.path.isfile(host_path_returned):
            os.remove(host_path_returned)
