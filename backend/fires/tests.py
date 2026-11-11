from django.test import SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    def test_public_health_contract(self):
        response = self.client.get("/api/v1/health/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "data_ready": False})

    def test_health_does_not_accept_writes(self):
        response = self.client.post("/api/v1/health/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 405)

    def test_only_approved_frontend_receives_cors_header(self):
        allowed = self.client.get("/api/v1/health/", HTTP_ORIGIN="http://localhost:3000")
        self.assertEqual(allowed["Access-Control-Allow-Origin"], "http://localhost:3000")
        other = self.client.get("/api/v1/health/", HTTP_ORIGIN="https://unrelated.example")
        self.assertNotIn("Access-Control-Allow-Origin", other)


class DemoCalendarTests(SimpleTestCase):
    def calendar_query(self, **overrides):
        params = {"region_id": "example-region", "year": 2024, "month": 8}
        params.update(overrides)
        return self.client.get("/api/v1/calendar/", params)

    def test_metadata_can_initialize_the_calendar(self):
        response = self.client.get("/api/v1/meta/")
        self.assertEqual(response.status_code, 200)
        meta = response.json()
        year, month, _ = map(int, meta["default_date"].split("-"))
        response = self.client.get("/api/v1/calendar/", {
            "region_id": meta["region_id"], "year": year, "month": month,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(meta["is_demo"])
        self.assertTrue(response.json()["is_demo"])
        self.assertEqual(meta["timezone"], "UTC")

    def test_calendar_has_all_days_and_distinguishes_zero_from_missing(self):
        response = self.calendar_query()
        self.assertEqual(response.status_code, 200)
        days = response.json()["days"]
        self.assertEqual(len(days), 31)
        self.assertEqual(days[0]["date"], "2024-08-01")
        self.assertEqual(days[-1]["date"], "2024-08-31")
        self.assertEqual(len({day["date"] for day in days}), 31)
        self.assertEqual(days[13]["modis_active_cells"], 12)
        self.assertEqual(days[13]["viirs_active_cells"], 18)
        self.assertEqual(days[14]["modis_active_cells"], 0)
        self.assertEqual(days[14]["viirs_active_cells"], 0)
        self.assertIsNone(days[15]["modis_active_cells"])
        self.assertIsNone(days[15]["viirs_active_cells"])

    def test_missing_and_unsupported_parameters_return_400(self):
        self.assertEqual(self.client.get("/api/v1/calendar/").status_code, 400)
        for invalid in [{"month": 13}, {"month": 7}, {"year": 0},
                        {"year": "invalid"}, {"region_id": "unknown"}]:
            with self.subTest(params=invalid):
                self.assertEqual(self.calendar_query(**invalid).status_code, 400)

    def test_demo_endpoints_are_read_only(self):
        for endpoint in ["meta", "calendar"]:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(f"/api/v1/{endpoint}/", {})
                self.assertEqual(response.status_code, 405)
