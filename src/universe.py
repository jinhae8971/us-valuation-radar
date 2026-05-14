"""
US Valuation Radar - Universe Definition
AI/Semiconductor + Big Tech focus (~150 tickers)

Curated as of 2026-05 by Younggil
- Semiconductor: 반도체 설계/제조/장비/메모리 전반
- AI Infrastructure: 데이터센터/클라우드/네트워킹
- Big Tech: Mag 7 + 주요 SaaS
- AI Native: AI-first 스타트업 (상장사)
- Power & Cooling: AI 데이터센터 인프라 (전력/냉각)
"""
from __future__ import annotations
from typing import Dict, List

# ---------------------------------------------------------------------------
# 섹터 분류는 GICS가 아닌 "투자 테마" 기준 (동종 비교를 더 정확하게)
# ---------------------------------------------------------------------------
UNIVERSE: Dict[str, List[str]] = {
    # ===== 반도체 (Semiconductor) =====
    "Semi - GPU/AI Accelerator": [
        "NVDA",   # NVIDIA
        "AMD",    # Advanced Micro Devices
        "AVGO",   # Broadcom
        "MRVL",   # Marvell
        "CBRS",   # Cerebras Systems (2026-05-14 IPO)
    ],
    "Semi - Foundry/IDM": [
        "TSM",    # Taiwan Semiconductor
        "INTC",   # Intel
        "GFS",    # GlobalFoundries
        "UMC",    # United Microelectronics
    ],
    "Semi - Memory": [
        "MU",     # Micron
        "WDC",    # Western Digital
        "STX",    # Seagate
    ],
    "Semi - Equipment": [
        "ASML",   # ASML Holding
        "AMAT",   # Applied Materials
        "LRCX",   # Lam Research
        "KLAC",   # KLA
        "TER",    # Teradyne
        "ENTG",   # Entegris
        "ONTO",   # Onto Innovation
        "ACMR",   # ACM Research
    ],
    "Semi - Analog/Mixed": [
        "TXN",    # Texas Instruments
        "ADI",    # Analog Devices
        "NXPI",   # NXP
        "MCHP",   # Microchip
        "ON",     # ON Semiconductor
        "MPWR",   # Monolithic Power
        "SWKS",   # Skyworks
        "QRVO",   # Qorvo
    ],
    "Semi - Networking/Custom": [
        "QCOM",   # Qualcomm
        "ARM",    # Arm Holdings
        "ALAB",   # Astera Labs
        "CRDO",   # Credo
    ],

    # ===== Big Tech (Mag 7 + 주요 메가캡) =====
    "Big Tech - Hyperscaler": [
        "MSFT",   # Microsoft
        "GOOGL",  # Alphabet
        "AMZN",   # Amazon
        "META",   # Meta
        "ORCL",   # Oracle
        "IBM",    # IBM
    ],
    "Big Tech - Consumer/Platform": [
        "AAPL",   # Apple
        "TSLA",   # Tesla
        "NFLX",   # Netflix
        "DIS",    # Disney
        "UBER",   # Uber
    ],

    # ===== AI Infrastructure / Cloud =====
    "Cloud - Neocloud/GPU-as-a-Service": [
        "CRWV",   # CoreWeave
        "NBIS",   # Nebius Group
        "APLD",   # Applied Digital
        "WULF",   # TeraWulf
        "IREN",   # IREN
    ],
    "Cloud - Networking/CDN": [
        "CSCO",   # Cisco
        "ANET",   # Arista Networks
        "JNPR",   # Juniper
        "NET",    # Cloudflare
        "FSLY",   # Fastly
        "AKAM",   # Akamai
    ],

    # ===== Software / SaaS / AI Application =====
    "Software - Enterprise SaaS": [
        "CRM",    # Salesforce
        "NOW",    # ServiceNow
        "ADBE",   # Adobe
        "INTU",   # Intuit
        "WDAY",   # Workday
        "SAP",    # SAP
        "TEAM",   # Atlassian
        "ZS",     # Zscaler
        "CRWD",   # CrowdStrike
        "PANW",   # Palo Alto Networks
        "FTNT",   # Fortinet
        "OKTA",   # Okta
        "DDOG",   # Datadog
        "SNOW",   # Snowflake
        "MDB",    # MongoDB
        "ESTC",   # Elastic
    ],
    "Software - AI/Data Native": [
        "PLTR",   # Palantir
        "AI",     # C3.ai
        "PATH",   # UiPath
        "BBAI",   # BigBear.ai
        "SOUN",   # SoundHound
    ],
    "Software - Dev Tools/Code": [
        "GTLB",   # GitLab
        "FROG",   # JFrog
        "S",      # SentinelOne
        "NET",    # Cloudflare
        "DBX",    # Dropbox
    ],

    # ===== Power, Energy, Cooling (AI Data Center 인프라) =====
    "Power - Generation/Utilities": [
        "VST",    # Vistra
        "CEG",    # Constellation Energy
        "TLN",    # Talen Energy
        "NRG",    # NRG Energy
    ],
    "Power - Equipment/Grid": [
        "ETN",    # Eaton
        "GEV",    # GE Vernova
        "VRT",    # Vertiv (cooling/power)
        "PWR",    # Quanta Services
        "PRIM",   # Primoris
    ],
    "Cooling/Thermal": [
        "MOD",    # Modine Manufacturing
        "SMCI",   # Super Micro
        "DELL",   # Dell
        "HPE",    # HPE
        "ANET",   # 이미 위에 있지만 중복 OK (dedup 처리됨)
    ],

    # ===== Quantum / Emerging Compute =====
    "Quantum/Emerging": [
        "IONQ",   # IonQ
        "RGTI",   # Rigetti
        "QBTS",   # D-Wave
        "ARQQ",   # Arqit
    ],

    # ===== Robotics / Autonomous =====
    "Robotics/Autonomous": [
        "ISRG",   # Intuitive Surgical
        "ABB",    # ABB
        "ROK",    # Rockwell Automation
        "PATH",   # UiPath (중복 OK)
        "SYM",    # Symbotic
    ],

    # ===== Internet / Ad-Tech =====
    "Internet/Ad-Tech": [
        "TTD",    # The Trade Desk
        "APP",    # AppLovin
        "RDDT",   # Reddit
        "PINS",   # Pinterest
        "SNAP",   # Snap
        "SPOT",   # Spotify
        "RBLX",   # Roblox
        "DUOL",   # Duolingo
    ],
}


# ---------------------------------------------------------------------------
# Super-sector 매핑: 작은 섹터들을 더 큰 비교 그룹으로 묶음
# Z-score 계산에는 super_sector를 사용 (최소 5개 이상 보장)
# 표시에는 sector(세부) 사용
# ---------------------------------------------------------------------------
SUPER_SECTOR_MAP: Dict[str, str] = {
    # Semiconductor — 하드웨어 전반은 함께 비교
    "Semi - GPU/AI Accelerator": "Semiconductor - Logic/Compute",
    "Semi - Foundry/IDM":        "Semiconductor - Logic/Compute",
    "Semi - Networking/Custom":  "Semiconductor - Logic/Compute",
    "Semi - Analog/Mixed":       "Semiconductor - Logic/Compute",

    "Semi - Memory":             "Semiconductor - Memory/Storage",

    "Semi - Equipment":          "Semiconductor - Equipment/Materials",

    # Big Tech — Mag7급은 자체적으로 비교
    "Big Tech - Hyperscaler":         "Mega Cap Tech",
    "Big Tech - Consumer/Platform":   "Mega Cap Tech",

    # Cloud / Networking 인프라
    "Cloud - Neocloud/GPU-as-a-Service": "AI Infrastructure Services",
    "Cloud - Networking/CDN":            "AI Infrastructure Services",

    # Software — SaaS 전반
    "Software - Enterprise SaaS":  "Software - SaaS/Security",
    "Software - Dev Tools/Code":   "Software - SaaS/Security",
    "Software - AI/Data Native":   "Software - AI Pure-Play",

    # Power & Cooling — AI 데이터센터 인프라
    "Power - Generation/Utilities": "Power & Datacenter Infra",
    "Power - Equipment/Grid":       "Power & Datacenter Infra",
    "Cooling/Thermal":              "Power & Datacenter Infra",

    # Emerging
    "Quantum/Emerging":      "Emerging Tech",
    "Robotics/Autonomous":   "Emerging Tech",
    "Internet/Ad-Tech":      "Internet / Consumer Tech",
}


def get_super_sector(sector: str) -> str:
    """세부 섹터 → 메타 섹터"""
    return SUPER_SECTOR_MAP.get(sector, sector)


def get_ticker_to_super_sector() -> Dict[str, str]:
    """티커 → 메타 섹터 매핑"""
    base = get_ticker_to_sector()
    return {t: get_super_sector(s) for t, s in base.items()}


def get_all_tickers() -> List[str]:
    """전체 종목 리스트 (중복 제거)"""
    seen = set()
    result = []
    for tickers in UNIVERSE.values():
        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result


def get_ticker_to_sector() -> Dict[str, str]:
    """티커 → 섹터 매핑 (첫 등장 섹터 기준)"""
    mapping = {}
    for sector, tickers in UNIVERSE.items():
        for t in tickers:
            if t not in mapping:
                mapping[t] = sector
    return mapping


def get_sector_tickers(sector: str) -> List[str]:
    return UNIVERSE.get(sector, [])


if __name__ == "__main__":
    all_t = get_all_tickers()
    print(f"Total unique tickers: {len(all_t)}")
    print(f"Sectors: {len(UNIVERSE)}")
    for sec, ts in UNIVERSE.items():
        print(f"  {sec:40s}: {len(ts):3d}")
