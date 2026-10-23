import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mpv_embed import MpvController


class FakeTransport:
    def __init__(self, lines=None):
        self.written = []
        self.requests = []
        self._lines = list(lines or [])
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data.decode("utf-8"))

    def request(self, data: bytes) -> bytes:
        self.requests.append(data.decode("utf-8"))
        if not self._lines:
            return b""
        return (self._lines.pop(0) + "\n").encode("utf-8")

    def ready(self) -> bool:
        return bool(self._lines)

    def readline(self) -> bytes:
        if not self._lines:
            return b""
        return (self._lines.pop(0) + "\n").encode("utf-8")

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self):
        self.alive = True
        self.terminated = False
        self.args = None

    def poll(self):
        return None if self.alive else 1

    def terminate(self):
        self.terminated = True
        self.alive = False


class FakeScheduler:
    def __init__(self):
        self.calls = []

    def __call__(self, delay_ms, fn):
        self.calls.append((delay_ms, fn))

    @property
    def delays(self):
        return [d for d, _ in self.calls]

    def run_last(self):
        self.calls[-1][1]()


def make_controller(lines=None):
    transport = FakeTransport(lines)
    proc = FakeProcess()
    sched = FakeScheduler()
    events = []

    def spawner(args):
        proc.args = list(args)
        return proc

    ctl = MpvController(
        mpv_path="mpv-fake",
        spawner=spawner,
        transport_factory=lambda pipe_name: transport,
        scheduler=sched,
        on_event=events.append,
    )
    ctl.start(hwnd=1234)
    return ctl, transport, proc, sched, events


class StartAndCommands(unittest.TestCase):
    def test_start_passes_wid_and_ipc_server(self):
        _ctl, _t, proc, _s, _e = make_controller()
        self.assertIn("--wid=1234", proc.args)
        self.assertTrue(any(a.startswith("--input-ipc-server=") for a in proc.args))

    def test_second_start_terminates_the_first_process(self):
        first = FakeProcess()
        second = FakeProcess()
        spawned = [first, second]
        ctl = MpvController(
            mpv_path="mpv-fake",
            spawner=lambda args: spawned.pop(0),
            transport_factory=lambda pipe_name: FakeTransport(),
            scheduler=FakeScheduler(),
        )
        ctl.start(hwnd=1)
        ctl.start(hwnd=1)
        self.assertTrue(first.terminated)
        self.assertFalse(second.terminated)

    def test_command_serializes_a_json_line(self):
        ctl, transport, _p, _s, _e = make_controller()
        ctl.command("set", "volume", 60)
        self.assertEqual(transport.written,
                         [json.dumps({"command": ["set", "volume", 60]}) + "\n"])

    def test_get_property_returns_the_data_field(self):
        ctl, _t, _p, _s, _e = make_controller(
            lines=['{"data": 60, "error": "success"}'])
        self.assertEqual(ctl.get_property("volume"), 60)

    def test_get_property_reads_the_response_on_its_own_connection(self):
        ctl, transport, _p, _s, _e = make_controller(
            lines=['{"data": 60, "error": "success"}'])
        ctl.get_property("volume")
        self.assertEqual(
            transport.requests,
            [json.dumps({"command": ["get_property", "volume"]}) + "\n"])
        self.assertEqual(transport.written, [])

    def test_pump_dispatches_parsed_events(self):
        ctl, _t, _p, _s, events = make_controller(
            lines=['{"event": "playback-restart"}', '{"event": "eof-reached"}'])
        ctl.pump_events()
        self.assertEqual(events, [{"event": "playback-restart"},
                                  {"event": "eof-reached"}])

    def test_load_sends_url_and_headers(self):
        ctl, transport, _p, _s, _e = make_controller()
        ctl.load("http://example/x.flv",
                 headers={"User-Agent": "UA1", "Referer": "https://huya.com/"})
        blob = "".join(transport.written)
        self.assertIn('"loadfile"', blob)
        self.assertIn("http://example/x.flv", blob)
        self.assertIn("User-Agent: UA1", blob)
        self.assertIn("Referer: https://huya.com/", blob)

    def test_stop_quits_then_terminates(self):
        ctl, transport, proc, _s, _e = make_controller()
        ctl.stop()
        self.assertIn(json.dumps({"command": ["quit"]}) + "\n", transport.written)
        self.assertTrue(proc.terminated)


class Reconnect(unittest.TestCase):
    def _fail_and_poll(self, ctl, proc, sched):
        proc.alive = False
        ctl.poll()
        sched.run_last()

    def test_backoff_follows_the_approved_ladder(self):
        ctl, _t, proc, sched, _e = make_controller()
        ctl.load("http://example/x.flv")
        for _ in range(6):
            self._fail_and_poll(ctl, proc, sched)
        self.assertEqual(sched.delays, [2000, 4000, 8000, 16000, 30000, 30000])

    def test_backoff_resets_after_playback_restart(self):
        ctl, transport, proc, sched, _e = make_controller(
            lines=['{"event": "playback-restart"}'])
        ctl.load("http://example/x.flv")
        self._fail_and_poll(ctl, proc, sched)
        self._fail_and_poll(ctl, proc, sched)
        ctl.pump_events()
        self._fail_and_poll(ctl, proc, sched)
        self.assertEqual(sched.delays, [2000, 4000, 2000])

    def test_no_reconnect_after_user_stop(self):
        ctl, _t, proc, sched, _e = make_controller()
        ctl.load("http://example/x.flv")
        ctl.stop()
        proc.alive = False
        ctl.poll()
        self.assertEqual(sched.calls, [])

    def test_reconnect_reloads_the_last_url(self):
        ctl, transport, proc, sched, _e = make_controller()
        ctl.load("http://example/x.flv")
        transport.written.clear()
        self._fail_and_poll(ctl, proc, sched)
        self.assertIn("http://example/x.flv", "".join(transport.written))

    def test_reconnect_keeps_the_spawn_extra_args(self):
        transport = FakeTransport()
        proc = FakeProcess()
        sched = FakeScheduler()
        ctl = MpvController(
            mpv_path="mpv-fake",
            spawner=lambda args: (setattr(proc, "args", list(args)), proc)[1],
            transport_factory=lambda pipe_name: transport,
            scheduler=sched,
        )
        ctl.start(hwnd=99, extra_args=("--cache=yes",))
        proc.alive = False
        ctl.poll()
        sched.run_last()
        self.assertIn("--cache=yes", proc.args)
        self.assertIn("--wid=99", proc.args)


if __name__ == "__main__":
    unittest.main()
