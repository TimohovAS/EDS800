"""Bounds one parameter takes from another: write order and refusals."""

import unittest

from enc_editor.catalog import load_catalog
from enc_editor.codecs import encode_value
from enc_editor.dependencies import Dependency, dependencies, order_writes
from enc_editor.session import Session, WriteTarget

CATALOG = load_catalog()


def codes(targets):
    return [target.code for target in targets]


class DependencyDataTests(unittest.TestCase):
    def test_profiles_state_the_frequency_and_vf_bounds(self):
        by_code = CATALOG["en600_v5"].by_code()
        self.assertEqual(
            dependencies(by_code["F01.01"]), (Dependency("F01.01", "F01.11", "maximum"),)
        )
        # A V/F corner point is fenced in from both sides.
        self.assertEqual(
            set(dependencies(by_code["F03.08"])),
            {
                Dependency("F03.08", "F03.06", "minimum"),
                Dependency("F03.08", "F03.10", "maximum"),
            },
        )

    def test_a_profile_without_such_bounds_is_left_alone(self):
        self.assertFalse(
            [
                parameter["code"]
                for parameter in CATALOG["eds800"].parameters
                if dependencies(parameter)
            ]
        )


class WriteOrderTests(unittest.TestCase):
    """The order a batch reaches the drive in."""

    def setUp(self):
        self.profile = CATALOG["en600_v5"]
        self.session = Session(self.profile)
        self.by_code = self.profile.by_code()

    def edit(self, values):
        self.session.edited.update(values)

    def targets(self):
        parameters = self.session.group_parameters("F01") + self.session.group_parameters("F03")
        targets, problems = self.session.collect_write_targets(parameters, edited_only=True)
        return targets, problems

    def test_a_rising_upper_limit_is_written_before_what_it_frees(self):
        # The reported failure: F01.01 sits at a lower address, so the batch
        # used to reach it while the drive still held the 50.00 Hz limit.
        self.session.apply_read({"F01.01": 5000, "F01.11": 5000})
        self.edit({"F01.01": "90.00", "F01.11": "90.00"})
        targets, problems = self.targets()
        self.assertEqual(problems, [])
        self.assertEqual(codes(targets), ["F01.11", "F01.01"])

    def test_a_falling_upper_limit_is_written_after_what_it_confines(self):
        self.session.apply_read({"F01.01": 9000, "F01.11": 9000})
        self.edit({"F01.01": "30.00", "F01.11": "40.00"})
        targets, problems = self.targets()
        self.assertEqual(problems, [])
        self.assertEqual(codes(targets), ["F01.01", "F01.11"])

    def test_a_value_beyond_a_limit_nobody_moves_is_refused_not_sent(self):
        self.session.apply_read({"F01.01": 5000, "F01.11": 5000})
        self.edit({"F01.01": "90.00"})
        targets, problems = self.targets()
        self.assertEqual(codes(targets), [])
        self.assertEqual([code for code, _ in problems], ["F01.01"])
        problem = problems[0][1]
        self.assertEqual(problem.key, "valid.maximum_from")
        self.assertEqual(problem.params["code"], "F01.11")
        self.assertEqual(problem.params["limit"], "50.00")

    def test_a_limit_that_was_never_read_is_left_to_the_drive(self):
        self.edit({"F01.01": "90.00"})
        targets, problems = self.targets()
        self.assertEqual(codes(targets), ["F01.01"])
        self.assertEqual(problems, [])

    def test_the_vf_chain_is_written_outwards(self):
        # Every corner point moves up, so each one needs the point above it
        # widened first: the chain has to be written from the top down.
        self.session.apply_read({"F03.04": 1000, "F03.06": 2000, "F03.08": 2500, "F03.10": 4000})
        self.edit({"F03.04": "30.00", "F03.06": "40.00", "F03.08": "45.00", "F03.10": "50.00"})
        targets, _problems = self.targets()
        self.assertEqual(codes(targets), ["F03.10", "F03.08", "F03.06", "F03.04"])

    def test_writing_the_factory_settings_back_changes_nothing_about_the_order(self):
        # "Write all" over a drive that is still at its factory values: every
        # bound already holds, so the batch must keep its address order and
        # its full length.
        parameters = [
            parameter
            for parameter in self.profile.parameters
            if not parameter.get("read_only") and parameter["default"]
        ]
        self.session.apply_read(
            {p["code"]: encode_value(p, p["default"]) for p in parameters}
        )
        targets, problems = self.session.collect_write_targets(parameters)
        self.assertEqual(problems, [])
        # Reset and copy actions are never replayed from a read-back value.
        expected = [p for p in parameters if not p.get("write_only_if_edited")]
        self.assertEqual(len(targets), len(expected))
        self.assertEqual(codes(targets), sorted(codes(targets), key=self._address))

    def _address(self, code):
        return self.by_code[code]["address"]


class ContradictoryRulesTests(unittest.TestCase):
    """A profile may still be wrong; a write must not vanish because of it."""

    def _target(self, code, address, **extra):
        parameter = {
            "code": code,
            "address": address,
            "scale": 1,
            "unit": "",
            "encoding": "numeric",
            "read_only": False,
            **extra,
        }
        return WriteTarget(parameter, 10, "10")

    def test_a_cycle_keeps_every_target(self):
        first = self._target("F1.00", 0x0100, maximum_from="F1.01")
        second = self._target("F1.01", 0x0101, maximum_from="F1.00")
        targets = [first, second]
        parameters = {target.code: target.parameter for target in targets}
        ordered = order_writes(targets, parameters, {})
        self.assertEqual(sorted(codes(ordered)), ["F1.00", "F1.01"])

    def test_a_bound_outside_the_batch_does_not_reorder_anything(self):
        targets = [
            self._target("F1.00", 0x0100, maximum_from="F1.09"),
            self._target("F1.01", 0x0101),
        ]
        parameters = {target.code: target.parameter for target in targets}
        self.assertEqual(codes(order_writes(targets, parameters, {})), ["F1.00", "F1.01"])


if __name__ == "__main__":
    unittest.main()
