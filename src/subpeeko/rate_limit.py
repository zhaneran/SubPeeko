"""Per-process request pacing and conservative rolling token reservations."""

from collections import deque
from threading import Lock
from time import monotonic, sleep


class RateLimiter:
    def __init__(self, rpm: int, tpm: int, qps: float | None = None):
        # Leave room for estimation error and other users of a shared quota.
        self.rpm = max(1, int(rpm * 0.8))
        self.tpm = max(1, int(tpm * 0.8))
        self.qps = min(qps if qps is not None else rpm / 60, rpm / 60) * 0.8
        self.events = deque()
        self.next_request = 0.0
        self.lock = Lock()

    def acquire(self, tokens: int):
        if tokens > self.tpm:
            raise ValueError("Estimated tokens for one request exceed the configured TPM budget")
        while True:
            with self.lock:
                now = monotonic()
                while self.events and self.events[0][0] <= now - 60:
                    self.events.popleft()
                delay = max(0.0, self.next_request - now)
                if len(self.events) >= self.rpm:
                    delay = max(delay, self.events[0][0] + 60 - now)
                excess = sum(event[1] for event in self.events) + tokens - self.tpm
                if excess > 0:
                    for timestamp, reserved in self.events:
                        excess -= reserved
                        if excess <= 0:
                            delay = max(delay, timestamp + 60 - now)
                            break
                if delay <= 0:
                    ticket = [now, tokens]
                    self.events.append(ticket)
                    self.next_request = now + max(1 / self.qps, 60 / self.rpm, 60 * tokens / self.tpm)
                    return ticket
            sleep(delay)

    def adjust(self, ticket, used: int) -> None:
        with self.lock:
            ticket[1] = max(ticket[1], used)

    def defer(self, seconds: float) -> None:
        with self.lock:
            self.next_request = max(self.next_request, monotonic() + seconds)
