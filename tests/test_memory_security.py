import math

from test_support import WorkersGroupTestCase


class MemorySecurityTests(WorkersGroupTestCase):
    def test_known_secret_and_pii_markers_are_redacted(self):
        module = self.source_module("memory_guard.py")
        text = "token=sk-test-not-a-real-secret email=alice@example.com password=correct-horse-battery-staple"
        result = module.redact_and_validate(text)
        self.assertFalse(result["accepted"])
        self.assertNotIn("sk-test-not-a-real-secret", result["redacted"])
        self.assertNotIn("alice@example.com", result["redacted"])

    def test_private_key_connection_string_and_high_entropy_are_rejected(self):
        module = self.source_module("memory_guard.py")
        samples = [
            "-----BEGIN PRIVATE KEY----- fake test marker -----END PRIVATE KEY-----",
            "postgresql://user:fake-password@localhost:5432/test",
            "entropy=QmFzZTY0VGhpcy1pcy1hLXRlc3Qtb25seS1zZWNyZXQ",
        ]
        for sample in samples:
            with self.subTest(sample=sample[:20]):
                self.assertFalse(module.redact_and_validate(sample)["accepted"])

    def test_test_fixture_strings_are_not_real_credentials(self):
        # These deliberately invalid markers make accidental secret reuse detectable in review.
        fixtures = ["sk-test-not-a-real-secret", "fake-password", "fake test marker"]
        self.assertTrue(all("fake" in value or "test" in value for value in fixtures))

    def test_generated_workers_group_task_ids_preserve_audit_provenance(self):
        module = self.source_module("memory_guard.py")
        task_id = "WG-frontmatter-verification-memory-reuse-dbf9ed5b0b99"
        result = module.redact_and_validate(task_id)
        self.assertTrue(result["accepted"], result)
        self.assertEqual(task_id, result["redacted"])

    def test_internal_sha256_fingerprint_is_not_scanned_as_phone_pii(self):
        module = self.source_module("memory_guard.py")
        fingerprint = "c1e221d17510ff992def0989830376c42c43d599d54e2f76b35c0d8710c9795c"
        result = module.redact_and_validate(
            f'{{"fingerprint":"{fingerprint}"}}'
        )
        self.assertTrue(result["accepted"], result)
        self.assertEqual([], result["findings"])
        self.assertIn(fingerprint, result["redacted"])
