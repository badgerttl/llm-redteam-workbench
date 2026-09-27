from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from prompt_mutator.audit import AuditBundle
from prompt_mutator.web import create_app


class WebAppContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_shell_catalog_and_security_headers_are_local_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = httpx.ASGITransport(app=create_app(runs_root=Path(directory)))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                shell = await client.get("/")
                catalog = await client.get("/api/catalog")

            self.assertEqual(shell.status_code, 200)
            self.assertIn("LLM Red Team Workbench", shell.text)
            self.assertIn('<dialog id="inspection-modal"', shell.text)
            self.assertIn('<dialog id="help-modal"', shell.text)
            self.assertIn('id="help-toggle"', shell.text)
            self.assertIn('id="close-inspection"', shell.text)
            self.assertIn("default-src 'self'", shell.headers["content-security-policy"])
            self.assertEqual(shell.headers["x-frame-options"], "DENY")
            self.assertEqual(catalog.status_code, 200)
            self.assertTrue(all(item["description"] for item in catalog.json()["profiles"]))
            self.assertEqual(len(catalog.json()["techniques"]), 17)
            technique_labels = {
                item["name"]: item["label"] for item in catalog.json()["techniques"]
            }
            self.assertEqual(technique_labels["html_entity"], "HTML Entity")
            self.assertEqual(technique_labels["url"], "URL")
            self.assertEqual(technique_labels["base64"], "Base64")
            self.assertIn("chained", {item["name"] for item in catalog.json()["profiles"]})

    async def test_generate_returns_inspectable_cases_and_retains_audit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = httpx.ASGITransport(app=create_app(runs_root=root))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json={
                        "prompt": "Review this café text",
                        "profile": "baseline",
                        "intensity": "medium",
                        "count": 25,
                    },
                )

            body = response.json()
            self.assertEqual(response.status_code, 200, body)
            self.assertEqual(len(body["cases"]), 25)
            self.assertIn("escaped", body["cases"][0])
            self.assertIn("encoded", body["cases"][0])
            self.assertNotEqual(body["cases"][0]["encoded"], body["cases"][0]["text"])
            self.assertTrue(body["cases"][0]["encoded"].startswith("\\u"))
            self.assertIn("code_points", body["cases"][0])
            bundle = root / body["run_id"]
            request, result = AuditBundle.load(bundle)
            self.assertEqual(request.prompt, "Review this café text")
            self.assertEqual(len(result.cases), 25)
            self.assertTrue(AuditBundle.verify(bundle).valid)

    async def test_custom_chain_preserves_exact_order_and_rejects_cross_origin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = httpx.ASGITransport(app=create_app(runs_root=Path(directory)))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json={
                        "prompt": "Apply this exact chain",
                        "profile": "custom_chain",
                        "intensity": "medium",
                        "count": 25,
                        "chain": ["leetspeak", "homoglyph", "hex"],
                    },
                )
                rejected = await client.post(
                    "/api/generate",
                    headers={"Origin": "https://attacker.example"},
                    json={
                        "prompt": "Do not accept this",
                        "profile": "baseline",
                        "intensity": "medium",
                        "count": 25,
                    },
                )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["cases"])
            self.assertTrue(
                all(
                    item["techniques"] == ["leetspeak", "homoglyph", "hex"]
                    for item in response.json()["cases"]
                )
            )
            self.assertEqual(rejected.status_code, 403)
            self.assertIn("Cross-origin", rejected.json()["error"])

    async def test_invalid_custom_selection_returns_readable_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = httpx.ASGITransport(app=create_app(runs_root=Path(directory)))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json={
                        "prompt": "Test this",
                        "profile": "custom",
                        "intensity": "medium",
                        "count": 25,
                        "techniques": [],
                    },
                )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["error"], "Select at least one custom technique")

    async def test_max_intensity_is_accepted_and_applies_everywhere_possible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            transport = httpx.ASGITransport(app=create_app(runs_root=Path(directory)))
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/api/generate",
                    json={
                        "prompt": "test",
                        "profile": "custom",
                        "intensity": "max",
                        "count": 25,
                        "techniques": ["leetspeak"],
                    },
                )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["cases"])
            self.assertTrue(
                all(case["changed_positions"] == [0, 1, 2, 3] for case in response.json()["cases"])
            )


if __name__ == "__main__":
    unittest.main()
