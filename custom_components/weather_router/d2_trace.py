"""Bounded, privacy-preserving one-shot diagnostic tracing for WeatherRouter D2."""
from __future__ import annotations
from collections import deque
from datetime import datetime, timezone
import re
from time import monotonic

CATEGORIES = frozenset(('provider','consumer','consumer_v1','consumer_v2','raster','runtime','routing','extension'))
STATES = frozenset(('start','success','failure','skipped','unavailable','recovered','unloaded'))
METRICS = frozenset(('duration_ms','event_loop_yield_ms','executor_turnaround_ms','http_status','response_bytes','declared_response_bytes','listing_pages','listing_objects_seen','listing_retry_count','buffered_event_count','receiver_count','direct_receiver_count','source_available','listing_complete','cache_hit','timeout','expected_absence','selected_count','candidate_count','fallback_count','frame_count','event_count','runtime_ready','enabled'))
_LIMIT = 240
_SAFE_ID = re.compile(r'^[a-zA-Z0-9_.-]{1,80}$')

def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def _metrics(data):
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, value in data.items():
        if key not in METRICS or type(value) not in (bool,int,float):
            continue
        if type(value) is float and (value != value or abs(value) > 1e12):
            continue
        if type(value) is int and abs(value) > 10**12:
            continue
        result[key] = value
    return result

class TraceStore:
    def __init__(self, limit=_LIMIT):
        if type(limit) is not int or not 1 <= limit <= _LIMIT:
            raise ValueError('invalid timeline limit')
        self._events = deque(maxlen=limit)
        self._sequence = 0

    def emit(self, category, state, *, correlation_id=None, source_id=None, metrics=None):
        if category not in CATEGORIES or state not in STATES:
            raise ValueError('invalid diagnostic event category or state')
        self._sequence += 1
        event = {'sequence':self._sequence,'utc':utc_now(), 'category':category,'state':state,'metrics':_metrics(metrics)}
        if isinstance(correlation_id,str) and _SAFE_ID.fullmatch(correlation_id):
            event['correlation_id'] = correlation_id
        if isinstance(source_id,str) and _SAFE_ID.fullmatch(source_id):
            event['source_id'] = source_id
        self._events.append(event)
        return event

    def snapshot(self, count=120):
        if type(count) is not int or not 0 <= count <= 120:
            raise ValueError('invalid snapshot limit')
        return list(self._events)[-count:] if count else []

    def __len__(self):
        return len(self._events)

class StageTimer:
    def __init__(self, store, category, correlation_id=None):
        self.store = store
        self.category = category
        self.correlation_id = correlation_id
        self.started = None
    def __enter__(self):
        self.started = monotonic()
        self.store.emit(self.category,'start',correlation_id=self.correlation_id)
        return self
    def __exit__(self, exception_type, exception, traceback):
        duration = round((monotonic()-self.started)*1000,2)
        self.store.emit(self.category,'failure' if exception_type else 'success',correlation_id=self.correlation_id,metrics={'duration_ms': duration})
        return False
