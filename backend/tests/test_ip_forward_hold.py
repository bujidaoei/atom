"""Exact-ID source name handoff and partial-failure recovery."""

from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy"))
import ip_forward_candidate as candidate  # noqa: E402
import ip_forward_hold as hold  # noqa: E402
import ip_forward_identity as identity  # noqa: E402
import ip_forward_stage as stage_module  # noqa: E402
import ip_forward_writers as writers  # noqa: E402
import protected_cutover  # noqa: E402


class ForwardHoldTest(TestCase):
    def setUp(self):
        self.config = protected_cutover.CutoverConfig(
            "atom-api", "atom-broker", Path("/old/data"), Path("/old/broker"),
            Path("/backup"), Path("/state"), "atom-network", 18080,
            18, 3, Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.revision = "a" * 40
        self.successor = "b" * 40
        self.ids = {role: f"{index:064x}" for index, role in
                    enumerate(identity.ROLES, 1)}
        self.held_names = {role: identity._name(self.config, role) +
                           "-forward-" + self.revision[:7]
                           for role in identity.ROLES}
        self.addresses = {"api": "172.30.0.8", "preview": "172.30.0.6",
                          "public": "172.30.0.7", "caddy": "172.30.0.4"}
        self.receipt = {"sourceRevision": self.revision,
                        "candidateDirectory": "/backup/forward-candidate-bbbbbbbbbbbb",
                        "containerIds": self.ids, "heldNames": self.held_names,
                        "serviceIps": self.addresses,
                        "caddy": {"base": "unused"}}
        self.containers = {role: {"Id": self.ids[role],
                                  "Name": "/" + identity._name(self.config, role),
                                  "State": {"Running": role == "caddy"}}
                           for role in identity.ROLES}
        log = Mock()
        log.read.return_value = {"phase": "captured"}
        log.identity_path = Path("/state/" + self.successor + ".forward.json")
        stopped = writers.StoppedWriters({role: self.ids[role]
                                          for role in writers.STOP_ORDER})
        self.stage = stage_module.ForwardStage(
            {"revision": self.revision, "containerIds": self.ids}, {}, (),
            stopped, Mock(), log, Mock())
        self.prepared = candidate.PreparedCandidate(
            Path(self.receipt["candidateDirectory"]), Path("/env"),
            Path("/api-env"), Path("/broker-env"), self.addresses["caddy"],
            self.addresses, "f" * 64)
        self.publication_file = Path.cwd() / "private-publication.env"
        self.events = []

    def _inspect(self, _config, expected_id, expected_name, *, running):
        item = next(value for value in self.containers.values()
                    if value["Id"] == expected_id)
        if (item["Name"] != "/" + expected_name
                or running is not None and item["State"]["Running"] is not running):
            raise hold.HoldError("forward_source_identity_changed")
        return item

    def _docker_inspect(self, _docker, _kind, expected_id):
        return next(value for value in self.containers.values()
                    if value["Id"] == expected_id)

    def _call(self, *, fault: str | None = None):
        renames = 0
        if fault == "journal_intent":
            def advance(phase):
                if phase == "candidate_intent":
                    raise hold.HoldError("injected_journal_failure")
            self.stage.journal.advance.side_effect = advance
        def run(_config, *arguments, timeout=60):
            nonlocal renames
            if arguments[:2] == ("container", "stop"):
                self.containers["caddy"]["State"]["Running"] = False
                self.events.append("stop")
                if fault == "stop_after_effect":
                    raise hold.HoldError("injected_timeout")
            elif arguments[:2] == ("container", "rename"):
                expected_id, new_name = arguments[2:]
                item = self._docker_inspect(None, None, expected_id)
                item["Name"] = "/" + new_name
                self.events.append("rename:" + new_name)
                renames += 1
                if fault == "rename_after_effect" and renames == 2:
                    raise hold.HoldError("injected_timeout")
            elif arguments[:2] == ("container", "start"):
                self.containers["caddy"]["State"]["Running"] = True
                self.events.append("start")
            else:
                raise AssertionError(arguments)
        def recovered(**_kwargs):
            self.events.append("source_recovered")
            self.stage.journal.advance("source_restored")
        with patch.object(hold.ip_forward_identity, "read",
                          return_value=self.receipt), \
             patch.object(hold.ip_forward_identity, "caddy_bytes",
                          return_value=b"base"), \
             patch.object(hold.ip_forward_candidate, "_source_handoff"), \
             patch.object(hold, "_inspect", side_effect=self._inspect), \
             patch.object(hold.protected_cutover, "_inspect",
                          side_effect=self._docker_inspect), \
             patch.object(hold, "_run", side_effect=run), \
             patch.object(hold.ip_forward_stage, "_recover_pre_exposure",
                          side_effect=recovered):
            if fault:
                with self.assertRaisesRegex(hold.HoldError,
                                            "forward_source_handoff_failed"):
                    hold.hold(config=self.config, stage=self.stage,
                              prepared=self.prepared,
                              successor_revision=self.successor,
                              publication_file=self.publication_file)
            else:
                receipt = hold.hold(config=self.config, stage=self.stage,
                    prepared=self.prepared, successor_revision=self.successor,
                    publication_file=self.publication_file)
                self.assertEqual(receipt.ids, self.ids)

    def test_held_names_retain_all_six_exact_stopped_ids(self):
        self._call()
        for role in identity.ROLES:
            self.assertEqual(self.containers[role]["Name"],
                             "/" + self.held_names[role])
            self.assertFalse(self.containers[role]["State"]["Running"])
        self.stage.journal.advance.assert_called_once_with("candidate_intent")

    def test_stop_timeout_after_effect_restores_caddy_and_source(self):
        self._call(fault="stop_after_effect")
        self.assertTrue(self.containers["caddy"]["State"]["Running"])
        self.assertEqual(self.events[-1], "source_recovered")
        self.assertEqual(self.stage.journal.advance.call_args_list[-1].args,
                         ("source_restored",))

    def test_rename_timeout_after_effect_restores_all_canonical_names(self):
        self._call(fault="rename_after_effect")
        for role in identity.ROLES:
            self.assertEqual(self.containers[role]["Name"],
                             "/" + identity._name(self.config, role))
        self.assertTrue(self.containers["caddy"]["State"]["Running"])
        self.assertEqual(self.events[-1], "source_recovered")

    def test_intent_failure_restores_source_without_stopping_caddy(self):
        self._call(fault="journal_intent")
        self.assertNotIn("stop", self.events)
        self.assertTrue(self.containers["caddy"]["State"]["Running"])
        self.assertEqual(self.events[-1], "source_recovered")


if __name__ == "__main__":
    main()
