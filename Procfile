# Worker count is pinned to 1 because SlidingWindowRateLimiter and
# AIConcurrencyGate (CampusIQ_career/api.py) are both process-local with no
# shared state. Running more than one worker silently multiplies both limits
# with no error or warning: N workers means N independent sliding windows and
# N independent concurrency semaphores, so the effective ceiling becomes N x
# the configured value and which worker a request lands on is nondeterministic.
#
# If horizontal scaling is ever needed, both must move to a shared external
# store (e.g. Redis) BEFORE workers or instances increase.
#
# A start command is not the only way a platform can set worker count --
# create_app() additionally rejects WEB_CONCURRENCY set to anything but "1",
# which this file alone would not catch.
web: uvicorn CampusIQ_career.api:app --host 0.0.0.0 --port $PORT --workers 1
