"""Costs are based on successful throughput; errors never inflate delivered capacity."""

import argparse
import json
from pathlib import Path


def cost_per_1000(hourly_usd, successful_requests, duration_seconds):
    if hourly_usd < 0 or successful_requests <= 0 or duration_seconds <= 0:
        raise ValueError("Need a nonnegative hourly price, positive successes and duration")
    return hourly_usd * duration_seconds / 3600 / successful_requests * 1000


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--hourly-usd", type=float, required=True, help="Total for every node")
    p.add_argument("--successful-requests", type=int, required=True)
    p.add_argument("--duration-seconds", type=float, required=True)
    p.add_argument("--price-source", required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.write_text(
        json.dumps(
            {
                "hourly_usd": a.hourly_usd,
                "price_source": a.price_source,
                "successful_requests": a.successful_requests,
                "duration_seconds": a.duration_seconds,
                "usd_per_1000": cost_per_1000(
                    a.hourly_usd, a.successful_requests, a.duration_seconds
                ),
            },
            indent=2,
        )
    )
