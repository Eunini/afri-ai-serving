"""Read public AWS offer files without Billing or Pricing API credentials.

Install ijson for streaming: the EC2 regional offer can be hundreds of MB.
The saved prices are list prices, independent of credits or free-tier coverage.
"""

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import ijson


def offer(service, region):
    url = f"https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/{service}/current/{region}/index.json"
    products, prices, metadata = {}, {}, {}
    attributes = {}
    with urllib.request.urlopen(url, timeout=120) as response:
        for prefix, event, value in ijson.parse(response):
            parts = prefix.split(".")
            if prefix in {"version", "publicationDate"} and event == "string":
                metadata[prefix] = value
            if len(parts) == 3 and parts[0] == "products" and parts[2] == "attributes":
                if event == "start_map":
                    attributes = {}
                elif event == "end_map":
                    compute = (
                        attributes.get("instanceType") in {"m7i.large", "m7i.xlarge", "m7i-flex.large", "c7i-flex.large"}
                        and attributes.get("operatingSystem") == "Linux"
                        and attributes.get("tenancy") == "Shared"
                        and attributes.get("preInstalledSw") == "NA"
                        and attributes.get("capacitystatus") == "Used"
                        and attributes.get("operation") == "RunInstances"
                    )
                    storage = attributes.get("usagetype") == "EBS:VolumeUsage.gp3"
                    ipv4 = attributes.get("usagetype") == "USE1-PublicIPv4:InUseAddress"
                    if compute or storage or ipv4:
                        products[parts[1]] = attributes.copy()
            elif len(parts) == 4 and parts[0] == "products" and parts[2] == "attributes":
                if event in {"string", "number"}:
                    attributes[parts[3]] = value
            if len(parts) >= 4 and parts[:2] == ["terms", "OnDemand"] and parts[2] in products:
                sku = parts[2]
                if event == "string" and parts[-1] in {
                    "USD",
                    "unit",
                    "effectiveDate",
                    "description",
                }:
                    prices.setdefault(sku, {})[parts[-1]] = value
    return {
        "url": url,
        **metadata,
        "products": [
            {"sku": sku, "attributes": attrs, "price": prices.get(sku)}
            for sku, attrs in products.items()
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    ec2 = offer("AmazonEC2", "us-east-1")
    vpc = offer("AmazonVPC", "us-east-1")
    records = ec2["products"] + vpc["products"]

    def price(predicate, unit):
        matches = [r for r in records if predicate(r["attributes"])]
        if len(matches) != 1 or not matches[0]["price"] or matches[0]["price"].get("unit") != unit:
            raise ValueError(f"Expected one unambiguous {unit} price; found {len(matches)}")
        return Decimal(matches[0]["price"]["USD"])

    disk = price(lambda x: x.get("usagetype") == "EBS:VolumeUsage.gp3", "GB-Mo")
    ip = price(lambda x: x.get("usagetype") == "USE1-PublicIPv4:InUseAddress", "Hrs")
    totals = {}
    for kind, count in [("m7i.xlarge", 1), ("m7i.large", 2), ("m7i-flex.large", 1), ("c7i-flex.large", 2)]:
        instance = price(lambda x: x.get("instanceType") == kind, "Hrs")
        hourly = count * (instance + ip + 30 * disk / 730)
        totals[f"{count}x{kind}"] = {
            "node_count": count,
            "ec2_usd_per_node_hour": float(instance),
            "ipv4_usd_per_node_hour": float(ip),
            "gp3_usd_per_gb_month": float(disk),
            "gp3_gb_per_node": 30,
            "monthly_to_hourly_convention_hours": 730,
            "cluster_usd_per_hour": float(hourly),
        }
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "region": "us-east-1",
        "currency": "USD",
        "sources": [ec2, vpc],
        "topologies": totals,
        "scope": "On-demand Linux compute + provisioned 30 GB/node gp3 + one public IPv4/node. Excludes tax and traffic charges; credits do not change list prices. No NAT or paid load balancer.",
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
