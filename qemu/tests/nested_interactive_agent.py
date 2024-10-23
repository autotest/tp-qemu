from virttest import error_context
from virttest.utils_test import VMStress

from provider import message_queuing


@error_context.context_aware
def run(test, params, env):
    """
    Control the life cycle of the guest through chat of remote MQ server

    Step:
     1) Launch a guest.
     2) Create a message queuing subscriber.
     3) Run stress tool in guest if necessary.
     4) Waiting for the MQ server to enter the "APPROVE" message.
     5) Reboot guest after received the message.
     6) Destroy the guest finally.

    :param test: Qemu test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    run_stress = params.get_boolean("run_stress")
    mq_publisher = params["mq_publisher"]
    mq_port = params.get("mq_port")
    wait_response_timeout = params.get_numeric("wait_response_timeout", 600)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()
    stress_tool = None

    if run_stress:
        stress_tool = VMStress(vm, "stress", params)
        stress_tool.load_stress_tool()

    mq_subscriber = message_queuing.MQSubscriber(mq_publisher, mq_port)

    try:
        error_context.context(
            'Receive the "APPROVE" message from MQ publisher ' "to continue the test.",
            test.log.info,
        )
        try:
            event = mq_subscriber.receive_event(wait_response_timeout)
            if event == "NOTIFY":
                test.log.warning('Got "NOTIFY" message to finish test')
                return
            elif event != "APPROVE":
                test.fail("Got unwanted message from MQ publisher.")
        except message_queuing.UnknownEventError as err:
            test.log.error(err)
            test.error(
                'The MQ publisher did not enter the "APPROVE" message '
                "within the expected time."
            )
        test.log.info('Already captured the "APPROVE" message.')

        if not stress_tool:
            vm.reboot()
    finally:
        if stress_tool:
            stress_tool.clean()
        vm.verify_kernel_crash()
        vm.destroy()
        mq_subscriber.close()
