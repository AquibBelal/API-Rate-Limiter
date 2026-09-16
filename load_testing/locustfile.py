from locust import HttpUser, task, between

class RateLimiterUser(HttpUser):
    wait_time = between(0.01, 0.05)  # Fast requests to trigger rate limiting

    @task(10)
    def test_rate_limited_endpoint(self):
        with self.client.get("/api/v1/resource", catch_response=True) as response:
            if response.status_code in (200, 429):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def test_health_bypass(self):
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure("Health check failed")