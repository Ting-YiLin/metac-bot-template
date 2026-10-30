"""Offline tests for exact question readback from grouped posts."""
from types import SimpleNamespace
import unittest

from s0_one_test import readback_selected_question


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.args = None

    def get_question_by_post_id(self, post_id, *, group_question_mode):
        self.args = (post_id, group_question_mode)
        return self.response


class ReadbackTests(unittest.TestCase):
    def test_group_post_matches_selected_question_id(self):
        selected = SimpleNamespace(id_of_post=43325, id_of_question=43330)
        client = FakeClient([
            SimpleNamespace(id_of_question=43329, already_forecasted=False),
            SimpleNamespace(id_of_question=43330, already_forecasted=True),
        ])

        self.assertTrue(readback_selected_question(client, selected))
        self.assertEqual(client.args, (43325, "unpack_subquestions"))

    def test_single_question_response_is_supported(self):
        selected = SimpleNamespace(id_of_post=7, id_of_question=9)
        client = FakeClient(SimpleNamespace(id_of_question=9, already_forecasted=False))

        self.assertFalse(readback_selected_question(client, selected))

    def test_missing_selected_question_is_an_error(self):
        selected = SimpleNamespace(id_of_post=43325, id_of_question=43330)
        client = FakeClient([SimpleNamespace(id_of_question=43329, already_forecasted=True)])

        with self.assertRaises(ValueError):
            readback_selected_question(client, selected)


if __name__ == "__main__":
    unittest.main()
