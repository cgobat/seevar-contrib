#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: core/preflight/aavso_fetcher.py
Version: 1.6.8
Objective: Haul AAVSO targets with nested dictionary support and strict error-message reporting.
"""

import json
import requests
import sys
import logging
import tomllib
from datetime import datetime
from pathlib import Path
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("AAVSO_Step1")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config.toml"
CATALOG_DIR = PROJECT_ROOT / "catalogs"
MASTER_HAUL_FILE = CATALOG_DIR / "campaign_targets.json"

MAG_LIMIT = 15.0
MIN_DEC = -7.62

def get_aavso_key():
    try:
        with open(CONFIG_PATH, "rb") as f:
            cfg = tomllib.load(f)
        key = cfg.get("aavso", {}).get("target_key")
        if not key or key == "":
            logger.error("❌ target_key is empty in config.toml")
            sys.exit(1)
        return key
    except Exception:
        logger.error("❌ Could not find [aavso] target_key in config.toml")
        sys.exit(1)

def haul_and_filter(api_key):
    endpoints = [
        "https://targettool.aavso.org/TargetTool/api/v1/targets",
        "https://filtergraph.com/aavso/api/v1/targets"
    ]
    
    raw_data = None
    
    for url in endpoints:
        logger.info(f"📡 Attempting connection to: {url}")
        try:
            response = requests.get(
                url, 
                auth=(api_key, "api_token"), 
                params={"obs_section": "all"}, 
                timeout=20
            )
            
            if response.status_code == 200:
                raw_data = response.json()
                break
            else:
                logger.warning(f"⚠️ Server returned {response.status_code} at {url}")
                
        except Exception as e:
            logger.warning(f"⚠️ Connection failed to {url}: {e}")
            continue

    if raw_data is None:
        logger.error("❌ All AAVSO endpoints failed to return a valid 200 OK response.")
        sys.exit(1)

    # Handle dictionary responses (either a single target, a nested list, or an error message)
    if isinstance(raw_data, dict):
        if 'star_name' in raw_data or 'name' in raw_data: 
            target_list = [raw_data]
        elif 'targets' in raw_data and isinstance(raw_data['targets'], list):
            target_list = raw_data['targets']
        else:
            logger.error(f"❌ API returned an unexpected dictionary (likely an error message):\n{json.dumps(raw_data, indent=2)}")
            sys.exit(1)
    elif isinstance(raw_data, list):
        target_list = raw_data
    else:
        logger.error(f"❌ Unexpected data format received: {type(raw_data)}")
        sys.exit(1)

    logger.info(f"📥 Processing {len(target_list)} raw entries...")

    targets_dict = {}
    
    for t in target_list:
        if not isinstance(t, dict):
            continue
            
        target_name = t.get('star_name') or t.get('name')
        if not target_name:
            continue

        try:
            mag = float(t.get('max_mag', 0))
            if mag > MAG_LIMIT or float(t.get('dec', -90)) < MIN_DEC:
                continue

            var_type = str(t.get('var_type', '')).upper()
            
            rec_cadence = 1 if any(x in var_type for x in ['CV', 'UG', 'RR', 'NA', 'ZAND', 'NL']) else 3

            canon_name = re.sub(r' V0+(\d)', r'V \1', str(target_name))
            
            if canon_name not in targets_dict or mag < targets_dict[canon_name]['max_mag']:
                targets_dict[canon_name] = {
                    "name": canon_name,
                    "ra": float(t.get('ra', 0)),
                    "dec": float(t.get('dec', 0)),
                    "type": var_type,
                    "max_mag": mag,
                    "recommended_cadence_days": rec_cadence,
                    "priority": 2,
                    "duration": 600
                }
        except (ValueError, TypeError):
            continue

    final_targets = list(targets_dict.values())

    if not final_targets:
        logger.error("❌ No valid targets remained after filtering.")
        sys.exit(1)

    output_data = {
        "metadata": {
            "generated": datetime.now().isoformat(),
            "source": "AAVSO Target Tool API",
            "target_count": len(final_targets)
        },
        "targets": final_targets
    }

    with open(MASTER_HAUL_FILE, "w") as f:
        json.dump(output_data, f, indent=4)

    logger.info(f"✅ Success: {len(final_targets)} unique targets saved to {MASTER_HAUL_FILE}")

if __name__ == "__main__":
    key = get_aavso_key()
    haul_and_filter(key)
