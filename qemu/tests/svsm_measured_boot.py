from virttest import error_context
from yaml import safe_load


@error_context.context_aware
def run(test, params, env):
    """
    Verify SVSM measured boot with builtin vTPM.

    This test validates the integrity of the boot process by:
    1. Obtaining a signed PCR quote from TPM2
    2. Verifying the quote signature with attestation key
    3. Extracting kernel hash from TPM event log
    4. Comparing it with the actual kernel image hash

    :param test: QEMU test object.
    :type  test: avocado_vt.test.VirtTest
    :param params: Dictionary with the test parameters.
    :type  params: virttest.utils_params.Params
    :param env: Dictionary with test environment.
    :type  env: virttest.utils_env.Env
    """

    def create_tpm2_keys():
        """Create TPM2 primary key and attestation key for PCR quote."""
        error_context.context("Create TPM2 keys", test.log.info)
        session.cmd("tpm2_createprimary -C o -g sha256 -G rsa -c primary.ctx")
        session.cmd("tpm2_create -C primary.ctx -g sha256 -G rsa -u ak.pub -r ak.priv")
        session.cmd("tpm2_load -C primary.ctx -u ak.pub -r ak.priv -c ak.ctx")

        test.log.info("TPM2 keys created successfully")

    def generate_nonce():
        """Generate a 16-byte random nonce for quote qualification."""
        error_context.context("Generate random nonce", test.log.info)
        session.cmd("dd if=/dev/urandom of=service_provider_nonce bs=16 count=1")
        size = session.cmd_output("stat -c %s service_provider_nonce").strip()
        if size != "16":
            test.fail(f"Nonce size incorrect: {size} (expected 16)")

        test.log.info("Random nonce generated (16 bytes)")

    def obtain_pcr_quote():
        """Obtain signed PCR quote from TPM2 for attestation verification."""
        error_context.context("Obtain PCR Quote", test.log.info)
        pcr_list = "sha1:0,1,2,3,4,5,6,7,8,9"
        test.log.info("Obtaining PCR Quote for: %s", pcr_list)

        session.cmd(
            "tpm2_quote "
            "--key-context ak.ctx "
            f"--pcr-list {pcr_list} "
            "--message pcr_quote.plain "
            "--signature pcr_quote.signature "
            "--qualification service_provider_nonce "
            "--hash-algorithm sha256 "
            "--pcr pcr.bin"
        )

        for f in ["pcr_quote.plain", "pcr_quote.signature", "pcr.bin"]:
            if session.cmd_status(f"test -f {f}") != 0:
                test.fail(f"Quote file not generated: {f}")

        test.log.info("PCR Quote obtained successfully")

    def verify_signature():
        """Verify the PCR quote signature using the attestation key."""
        error_context.context("Verify signature integrity", test.log.info)
        s, o = session.cmd_status_output(
            "tpm2_checkquote "
            "--public ak.pub "
            "--message pcr_quote.plain "
            "--signature pcr_quote.signature "
            "--qualification service_provider_nonce",
        )
        if s != 0:
            test.fail(f"Signature verification FAILED: {o}")
        test.log.info("Signature verification PASSED")

    def check_event_log(kernel_version, event_log_path):
        """
        Parse TPM event log and extract kernel hash from PCR 9.

        :param kernel_version: Kernel version string to locate in event log.
        :param event_log_path: Path to TPM binary event log.
        :return: SHA256 hash of kernel image from event log.
        """
        error_context.context("Check Event Log", test.log.info)
        event_log_yaml = session.cmd_output(f"tpm2_eventlog {event_log_path}")

        event_data = safe_load(event_log_yaml)
        events = event_data.get("events", [])
        target_vmlinuz = f"(hd0,gpt2)/vmlinuz-{kernel_version}"
        event_log_hash = None

        matching_event = next(
            (
                event
                for event in events
                if event.get("PCRIndex") == 9
                and event.get("EventType") == "EV_IPL"
                and event.get("Event", {}).get("String", "").find(target_vmlinuz) >= 0
            ),
            None,
        )

        if matching_event:
            event_log_hash = next(
                (
                    digest.get("Digest", "").strip('"').lower()
                    for digest in matching_event.get("Digests", [])
                    if digest.get("AlgorithmId") == "sha256"
                ),
                None,
            )

        if not event_log_hash:
            test.fail(f"Could not find {target_vmlinuz} in PCR 9 events")

        test.log.info("Event log verification passed")
        return event_log_hash

    def compare_kernel_hash(kernel_version, event_log_hash):
        """
        Verify kernel integrity by comparing actual hash with event log hash.

        :param kernel_version: Kernel version to verify.
        :param event_log_hash: Expected hash from TPM event log.
        """
        error_context.context("Compare kernel image hash", test.log.info)

        hash_output = session.cmd_output(f"sha256sum /boot/vmlinuz-{kernel_version}")
        kernel_hash = hash_output.split()[0].lower()

        # Compare hashes
        if kernel_hash != event_log_hash:
            test.fail(
                f"Kernel hash mismatch!\n"
                f"Kernel:    {kernel_hash}\n"
                f"Event log: {event_log_hash}"
            )

        test.log.info("Kernel hash verification PASSED")

    error_context.base_context("Boot SVSM VM", test.log.info)
    event_log_path = "/sys/kernel/security/tpm0/binary_bios_measurements"
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    kernel_version = session.cmd_output("uname -r").strip()

    try:
        create_tpm2_keys()
        generate_nonce()
        obtain_pcr_quote()
        verify_signature()
        event_log_hash = check_event_log(kernel_version, event_log_path)
        compare_kernel_hash(kernel_version, event_log_hash)
    finally:
        session.close()
        vm.destroy()
