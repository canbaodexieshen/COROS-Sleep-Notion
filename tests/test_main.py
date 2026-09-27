import json
import os
import unittest
from unittest.mock import patch

from src.main import _save_refreshed_token


class TokenPersistenceTests(unittest.TestCase):
    def test_writes_refreshed_token_without_logging_values(self):
        token_data = {
            "access_token": "new-access-secret",
            "refresh_token": "new-refresh-secret",
            "expires_at_epoch": 1800000000,
        }

        with patch.dict(
            os.environ,
            {"COROS_TOKEN_OUTPUT_FILE": "/runner-temp/coros-token.json"},
            clear=False,
        ), patch("src.main.Path") as mocked_path, patch(
            "builtins.print"
        ) as mocked_print:
            target = mocked_path.return_value
            temporary = target.with_suffix.return_value
            _save_refreshed_token(token_data)

        written_json = temporary.write_text.call_args.args[0]
        self.assertEqual(json.loads(written_json), token_data)
        temporary.replace.assert_called_once_with(target)
        printed = " ".join(
            str(argument)
            for call in mocked_print.call_args_list
            for argument in call.args
        )
        self.assertNotIn(token_data["access_token"], printed)
        self.assertNotIn(token_data["refresh_token"], printed)

    def test_does_not_log_values_without_output_file(self):
        token_data = {
            "access_token": "new-access-secret",
            "refresh_token": "new-refresh-secret",
            "expires_at_epoch": 1800000000,
        }

        with patch.dict(os.environ, {}, clear=True), patch(
            "builtins.print"
        ) as mocked_print:
            _save_refreshed_token(token_data)

        printed = " ".join(
            str(argument)
            for call in mocked_print.call_args_list
            for argument in call.args
        )
        self.assertNotIn(token_data["access_token"], printed)
        self.assertNotIn(token_data["refresh_token"], printed)


if __name__ == "__main__":
    unittest.main()
