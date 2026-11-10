import unittest
from src.mcp.xiaozhi_bridge import XiaoZhiMcpBridge
from src.devices.registry import get_robot_registry

class TestSecretRedaction(unittest.TestCase):
    def test_bridge_url_masking(self):
        url = "wss://api.xiaozhi.me/mcp/?token=secret_jwt_token_12345"
        masked = XiaoZhiMcpBridge.mask_url(url)
        self.assertNotIn("secret_jwt_token_12345", masked)
        self.assertEqual(masked, "wss://api.xiaozhi.me/mcp/?[REDACTED]")

        url_with_multiple_params = "wss://example.com/socket?device=esp32&token=supersecret&foo=bar"
        masked_multi = XiaoZhiMcpBridge.mask_url(url_with_multiple_params)
        self.assertNotIn("supersecret", masked_multi)
        self.assertIn("[REDACTED]", masked_multi)

    def test_registry_stores_no_private_keys(self):
        registry = get_robot_registry()
        with registry.store.connection() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(robot_keys)").fetchall()]
            self.assertIn("public_key", columns)
            self.assertIn("fingerprint", columns)
            self.assertNotIn("private_key", columns)
            self.assertNotIn("secret_key", columns)

    def test_enrollment_challenges_stores_no_private_keys(self):
        registry = get_robot_registry()
        with registry.store.connection() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(enrollment_challenges)").fetchall()]
            self.assertIn("id", columns)
            self.assertIn("display_code", columns)
            self.assertNotIn("private_key", columns)
            self.assertNotIn("secret_key", columns)

        print("\n===============================")
        print("SECRET_REDACTION_PASS")
        print("===============================\n")

if __name__ == "__main__":
    unittest.main()
