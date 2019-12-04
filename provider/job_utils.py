from functools import partial

from avocado import fail_on
from virttest import utils_misc


def get_job_status(vm, device):
    """
    Get block job state

    :param vm: VM object
    :param device: device ID or node-name

    return str: block job state string
    """
    job = get_job_by_id(vm, device)
    return job.get("status")


@fail_on
def wait_until_job_status_match(vm, status, device, timeout):
    """
    Block until job state match to expect state

    :param vm: VM object
    :param status: expect state string
    :param device: device ID or node-name
    :param timeout: blocked timeout
    """
    matched = utils_misc.wait_for(
        lambda: get_job_status(vm, device) == status,
        timeout=timeout)
    assert matched, "wait job status to '%s' timeout in %s seconds" % (
        status, timeout)


@fail_on
def wait_until_block_job_completed(vm, job_id, timeout=360):
    action_mapping = {"concluded": partial(block_job_dismiss, vm=vm, job_id=job_id),
                      "pending": partial(block_job_finalize, vm=vm, job_id=job_id)}

    completed_event = "BLOCK_JOB_COMPLETED"

    def _wait_until_block_job_completed():
        status = get_job_status(vm, job_id)
        if status in action_mapping:
            action_mapping[status]()
        vm.monitor.cmd("query-block-jobs")
        event = vm.monitor.get_event(completed_event)
        if not event:
            return False
        error = event["data"].get("error")
        assert not error, "block backup job finished with error: %s" % error
        return True

    finished = utils_misc.wait_for(
        _wait_until_block_job_completed,
        first=0.1,
        timeout=timeout)
    assert finished, "wait for block job complete event timeout in %s seconds" % timeout


def block_job_dismiss(vm, job_id, timeout=120):
    """
    Dismiss block job when job in concluded state
    """
    job = get_block_job_by_id(vm, job_id)
    if job.get("auto-dismiss", True) is False:
        return _job_dismiss(vm, job_id, True, timeout)


def job_dismiss(vm, job_id, timeout=120):
    """dismiss job when job status is concluded"""
    return _job_dismiss(vm, job_id, False, timeout)


@fail_on
def _job_dismiss(vm, job_id, is_block_job=False, timeout=120):
    """dismiss job when job status is concluded"""
    wait_until_job_status_match(vm, "concluded", job_id, timeout)
    cmd = "block-job-dismiss" if is_block_job else "job-dismiss"
    arguments = {"id": job_id}
    return vm.monitor.cmd(cmd, arguments)


def block_job_finalize(vm, job_id, timeout=120):
    """Finalize block job when job in pending state"""
    job = get_block_job_by_id(vm, job_id)
    if job.get("auto-finalize", True) is False:
        return _job_finalize(vm, job_id, True, timeout)


def job_finalize(vm, job_id, timeout=120):
    """Finalize job when job in pending state"""
    return _job_finalize(vm, job_id, False, timeout)


@fail_on
def _job_finalize(vm, job_id, is_block_job=False, timeout=120):
    """Finalize job when job in pending state"""
    wait_until_job_status_match(vm, "pending", job_id, timeout)
    cmd = "block-job-finalize" if is_block_job else "job-finalize"
    arguments = {"id": job_id}
    vm.monitor.cmd(cmd, arguments)


@fail_on
def get_job_by_id(vm, job_id):
    """Get block job info by job ID"""
    for job in query_jobs(vm):
        if job["id"] == job_id:
            return job
    return dict()


@fail_on
def get_block_job_by_id(vm, job_id):
    for job in query_block_jobs(vm):
        if job["device"] == job_id:
            return job
    return dict()


def query_jobs(vm):
    """Get block jobs info list in given VM"""
    return vm.monitor.cmd("query-jobs")


def query_block_jobs(vm):
    """Get jobs info list in given VM"""
    return vm.monitor.cmd("query-block-jobs")


def make_transaction_action(cmd, data):
    """
    Make transaction action dict by arguments
    """
    prefix = "x-"
    if not cmd.startswith(prefix):
        for k in data.keys():
            if data.get(k) is None:
                data.pop(k)
                continue
            if cmd == "block-dirty-bitmap-add" and k == "x-disabled":
                continue
            if k.startswith(prefix):
                data[k.lstrip(prefix)] = data.pop(k)
    return {"type": cmd, "data": data}
