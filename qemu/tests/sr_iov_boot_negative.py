from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    KVM boot with negative parameter test:
    1) Try to boot VM with negative parameters.
    2) Verify that qemu could handle the negative parameters.
       Check the negative message (optional)

    :param test: qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    neg_msg = params.get("negative_msg")
    if params.get("start_vm") == "yes":
        test.error("Please set start_vm to no")
    params["start_vm"] = "yes"
    try:
        error_context.context("Try to boot VM with negative parameters", test.log.info)
        case_fail = False
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        case_fail = True
    except Exception as e:
        if neg_msg:
            error_context.context("Check qemu-qemu error message", test.log.info)
            if neg_msg not in str(e):
                msg = "Could not find '%s' in error message '%s'" % (neg_msg, e)
                test.fail(msg)
        test.log.debug("Could not boot up vm, %s", e)
    if case_fail:
        test.fail("Did not raise exception during vm boot up")
