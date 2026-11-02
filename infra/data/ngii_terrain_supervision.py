"""Bounded native-crash retry policy; data/validation failures are never retried."""
NATIVE_ACCESS_VIOLATION=0xC0000005


def may_retry(exit_code,state,retries,failures_for_job):
    return ((exit_code & 0xffffffff)==NATIVE_ACCESS_VIOLATION
            and state in ('running','failed') and retries<3 and failures_for_job<3)
