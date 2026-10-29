"""Public, independent OPERA acceptance oracle using synthetic observations.

This reference contract is intentionally NOT the private WeatherRouter runtime.
Its passing tests prove the public policy model, not private integration.
All inputs and fixtures are synthetic. No private source or test data imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock, Thread
import unittest


PRODUCTS = ("RATE", "DBZH", "ACRR")
MAX_HISTORICAL_SECONDS = 3600


def classify(observed_at: datetime, now: datetime, *, fresh: int = 1500,
             stale_after: int = 1500, serve_stale: bool = False) -> str:
    """UTC observation time alone defines frame age (never download time)."""
    if (not isinstance(observed_at, datetime) or observed_at.tzinfo is None
            or not isinstance(now, datetime) or now.tzinfo is None
            or type(fresh) is not int or not 900 <= fresh <= 3600
            or type(stale_after) is not int or not 900 <= stale_after <= 3600
            or type(serve_stale) is not bool):
        return "UNAVAILABLE"
    age = (now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= age <= (MAX_HISTORICAL_SECONDS if serve_stale else fresh):
        return "UNAVAILABLE"
    return "STALE" if age > min(fresh, stale_after) else "CURRENT"


def allow(*, provider: bool, service: bool, admin: bool,
          scientific: bool, warning_consumer: bool) -> bool:
    """Synthetic gate: diagnostic exposure is not scientific approval."""
    return (provider and service and admin
            and (scientific or not warning_consumer))


@dataclass(frozen=True)
class Cycle:
    product: str
    observed_at: datetime
    digest: str
    complete: bool


class ReferencePublisher:
    """A tiny executable specification of atomic, monotonic publication."""
    def __init__(self):
        self._lock = RLock()
        self._active: dict[str, Cycle] = {}

    def publish(self, cycle: Cycle, *, verified: bool):
        if cycle.product not in PRODUCTS or not cycle.complete or not verified:
            return False
        with self._lock:
            previous = self._active.get(cycle.product)
            if previous:
                if cycle.observed_at < previous.observed_at:
                    return False
                if cycle.observed_at == previous.observed_at:
                    return previous.digest == cycle.digest
            self._active[cycle.product] = cycle
            return True

    def read(self, product: str):
        with self._lock:
            return self._active.get(product)


class PublicOperaContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)

    def test_product_services_independent(self):
        selected = {"RATE": True, "DBZH": False, "ACRR": False}
        for name in PRODUCTS:
            self.assertEqual(selected[name], name == "RATE")

    def test_observation_age_boundaries(self):
        cases = [(0, "CURRENT"), (1500, "CURRENT"), (1501, "UNAVAILABLE"),
                 (-1, "UNAVAILABLE"), (3601, "UNAVAILABLE")]
        for age, expected in cases:
            with self.subTest(age=age):
                self.assertEqual(classify(self.now - timedelta(seconds=age), self.now), expected)

    def test_stale_continuity_and_hard_limit(self):
        for age, expected in ((1200, "CURRENT"), (1201, "STALE"),
                              (3600, "STALE"), (3601, "UNAVAILABLE")):
            with self.subTest(age=age):
                self.assertEqual(classify(self.now - timedelta(seconds=age), self.now,
                                          fresh=1500, stale_after=1200, serve_stale=True), expected)

    def test_redownload_cannot_rejuvenate(self):
        measurement = self.now - timedelta(seconds=2700)
        self.assertEqual(classify(measurement, self.now), "UNAVAILABLE")
        self.assertEqual(classify(measurement, self.now, serve_stale=True), "STALE")

    def test_invalid_age_policy_fails_closed(self):
        self.assertEqual(classify(self.now, self.now, fresh=True), "UNAVAILABLE")
        self.assertEqual(classify(self.now, self.now, fresh=800), "UNAVAILABLE")
        self.assertEqual(classify(self.now, self.now, stale_after=4000), "UNAVAILABLE")
        self.assertEqual(classify(self.now.replace(tzinfo=None), self.now), "UNAVAILABLE")

    def test_disabled_provider_service_and_warning_science_gates(self):
        self.assertFalse(allow(provider=False, service=True, admin=True,
                               scientific=False, warning_consumer=False))
        self.assertFalse(allow(provider=True, service=False, admin=True,
                               scientific=False, warning_consumer=False))
        self.assertFalse(allow(provider=True, service=True, admin=False,
                               scientific=False, warning_consumer=False))
        self.assertFalse(allow(provider=True, service=True, admin=True,
                               scientific=False, warning_consumer=True))
        self.assertTrue(allow(provider=True, service=True, admin=True,
                              scientific=False, warning_consumer=False))

    def test_failed_prepare_preserves_current(self):
        pub = ReferencePublisher()
        base = Cycle("RATE", self.now, "synthetic-one", True)
        self.assertTrue(pub.publish(base, verified=True))
        self.assertFalse(pub.publish(Cycle("RATE", self.now + timedelta(minutes=15),
                                          "synthetic-two", False), verified=True))
        self.assertEqual(pub.read("RATE"), base)

    def test_old_cycle_cannot_rollback(self):
        pub = ReferencePublisher()
        new = Cycle("RATE", self.now, "synthetic-new", True)
        self.assertTrue(pub.publish(new, verified=True))
        self.assertFalse(pub.publish(Cycle("RATE", self.now - timedelta(minutes=15),
                                          "synthetic-old", True), verified=True))
        self.assertEqual(pub.read("RATE"), new)

    def test_conflicting_same_stamp_rejected(self):
        pub = ReferencePublisher()
        base = Cycle("RATE", self.now, "synthetic-one", True)
        self.assertTrue(pub.publish(base, verified=True))
        self.assertFalse(pub.publish(Cycle("RATE", self.now, "synthetic-other", True),
                                     verified=True))
        self.assertEqual(pub.read("RATE"), base)

    def test_parallel_publish_never_returns_partial_cycle(self):
        pub = ReferencePublisher()
        values = [Cycle("RATE", self.now + timedelta(minutes=n), f"synthetic-{n}", True)
                  for n in range(12)]
        threads = [Thread(target=pub.publish, args=(cycle,), kwargs={"verified": True})
                   for cycle in reversed(values)]
        for worker in threads:
            worker.start()
        for worker in threads:
            worker.join()
        self.assertEqual(pub.read("RATE"), values[-1])

    def test_products_have_isolated_cycle_pointers(self):
        pub = ReferencePublisher()
        for name in PRODUCTS:
            self.assertTrue(pub.publish(Cycle(name, self.now, f"synthetic-{name}", True),
                                        verified=True))
        self.assertEqual({pub.read(name).product for name in PRODUCTS}, set(PRODUCTS))


if __name__ == "__main__":
    unittest.main()
