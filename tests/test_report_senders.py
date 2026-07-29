import os
import sys
import tempfile
import unittest
from email.message import EmailMessage
from io import StringIO
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import send_email_report  # noqa: E402
import send_whatsapp_report  # noqa: E402


class SenderConfigTest(unittest.TestCase):
    def test_email_fails_closed_and_lists_all_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {}, clear=True
        ), patch.object(
            send_email_report, "CONFIG_PATH", Path(tmp) / "missing.env"
        ):
            config, missing = send_email_report.load_config()
        self.assertIsNone(config)
        self.assertEqual(missing, list(send_email_report.REQUIRED_KEYS))

    def test_whatsapp_defaults_to_cloud_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {}, clear=True
        ), patch.object(
            send_whatsapp_report, "CONFIG_PATH", Path(tmp) / "missing.env"
        ):
            config, missing = send_whatsapp_report.load_config()
        self.assertEqual(config["REPORT_WHATSAPP_PROVIDER"], "cloud_api")
        self.assertEqual(
            missing,
            [
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_TOKEN",
                "REPORT_WHATSAPP_TO",
            ],
        )

    def test_whatsapp_rejects_unknown_provider(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"REPORT_WHATSAPP_PROVIDER": "provider_invalido"},
            clear=True,
        ), patch.object(
            send_whatsapp_report, "CONFIG_PATH", Path(tmp) / "missing.env"
        ):
            with self.assertRaisesRegex(ValueError, "cloud_api, evolution"):
                send_whatsapp_report.load_config()

    def test_number_mask_exposes_only_last_four_digits(self):
        self.assertEqual(send_whatsapp_report.mask_number("ab12-cd34-ef56"), "****3456")

    def test_email_dry_run_does_not_call_smtp(self):
        message = EmailMessage()
        message.set_content("relatório de teste")
        with patch.object(
            send_email_report, "load_config", return_value=({}, [])
        ), patch.object(
            send_email_report, "build_message", return_value=message
        ), patch.object(
            send_email_report, "send_message"
        ) as sender, patch.object(
            sys, "argv", ["send_email_report.py", "--dry-run"]
        ), patch(
            "sys.stdout", new_callable=StringIO
        ):
            result = send_email_report.main()
        self.assertEqual(result, 0)
        sender.assert_not_called()

    def test_whatsapp_dry_run_does_not_call_provider(self):
        config = {
            "REPORT_WHATSAPP_PROVIDER": "cloud_api",
            "REPORT_WHATSAPP_TO": "destino_de_teste",
            "REPORT_WINDOW": None,
        }
        report = {
            "available": False,
            "warning": "dados indisponíveis",
            "account": "conta de teste",
            "window": 7,
            "generated_display": "coleta indisponível",
            "campaigns": [],
            "scale_ads": [],
            "kill_ads": [],
            "footer": "fonte local",
        }
        with patch.object(
            send_whatsapp_report, "load_config", return_value=(config, [])
        ), patch.object(
            send_whatsapp_report, "assemble_report", return_value=report
        ), patch.object(
            send_whatsapp_report, "send_cloud_api"
        ) as cloud_sender, patch.object(
            sys, "argv", ["send_whatsapp_report.py", "--dry-run"]
        ), patch(
            "sys.stdout", new_callable=StringIO
        ):
            result = send_whatsapp_report.main()
        self.assertEqual(result, 0)
        cloud_sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
