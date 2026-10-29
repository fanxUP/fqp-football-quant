"""博彩公司分级目录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

# company_id 为负数/0 的是站方暂未返回赔率、但需要建档的品牌；
# 中国体彩的数据在 jc_odds 表，不进入 odds 表。
SEED: list[dict[str, Any]] = [
    # 第一梯队：赔率基准
    {
        "company_id": 177,
        "name": "Pinnacle 平博",
        "name_full": "Pinnacle",
        "tier": "tier1",
        "category": "sharp",
        "brand": "Pinnacle",
        "region": "荷兰",
        "is_exchange": 0,
        "note": "低抽水、高限额，职业玩家与模型的赔率基准",
    },
    {
        "company_id": 2,
        "name": "Betfair",
        "name_full": "Betfair",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "英国",
        "is_exchange": 1,
        "note": "交易所，价格接近真实概率",
    },
    {
        "company_id": 988,
        "name": "Betfair Sportsbook",
        "name_full": "Betfair Sportsbook",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "英国",
        "is_exchange": 1,
        "note": "Betfair 体育书",
    },
    {
        "company_id": 1036,
        "name": "Betfair AU",
        "name_full": "Betfair Australia",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "澳大利亚",
        "is_exchange": 1,
        "note": "Betfair 澳洲交易所",
    },
    {
        "company_id": 1055,
        "name": "Betfair Exchange",
        "name_full": "Betfair Exchange",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "英国",
        "is_exchange": 1,
        "note": "交易所主站",
    },
    {
        "company_id": 1599,
        "name": "Betfair Exchange ES",
        "name_full": "Betfair Exchange Spain",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "西班牙",
        "is_exchange": 1,
        "note": "",
    },
    {
        "company_id": 1600,
        "name": "Betfair Exchange AU",
        "name_full": "Betfair Exchange Australia",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "澳大利亚",
        "is_exchange": 1,
        "note": "",
    },
    {
        "company_id": 1601,
        "name": "Betfair ES",
        "name_full": "Betfair Spain",
        "tier": "tier1",
        "category": "exchange",
        "brand": "Betfair",
        "region": "西班牙",
        "is_exchange": 1,
        "note": "",
    },
    # 第二梯队：主流大公司
    {
        "company_id": 537,
        "name": "bet365",
        "name_full": "bet365",
        "tier": "tier2",
        "category": "mainstream",
        "brand": "bet365",
        "region": "英国",
        "is_exchange": 0,
        "note": "全球最大在线博彩之一，盘口全、限额高",
    },
    {
        "company_id": 115,
        "name": "William Hill 威廉希尔",
        "name_full": "William Hill",
        "tier": "tier2",
        "category": "mainstream",
        "brand": "William Hill",
        "region": "英国",
        "is_exchange": 0,
        "note": "英国老牌，欧赔参考价值高",
    },
    {
        "company_id": 82,
        "name": "Ladbrokes 立博",
        "name_full": "Ladbrokes",
        "tier": "tier2",
        "category": "mainstream",
        "brand": "Ladbrokes",
        "region": "英国",
        "is_exchange": 0,
        "note": "英国老牌，传统欧赔基准",
    },
    {
        "company_id": 3,
        "name": "Crown 皇冠",
        "name_full": "Crown",
        "tier": "tier2",
        "category": "asian",
        "brand": "Crown",
        "region": "亚洲",
        "is_exchange": 0,
        "note": "亚洲盘口风向标，亚让/大小球变化参考",
    },
    {
        "company_id": 545,
        "name": "Crown 皇冠",
        "name_full": "Crown (alt)",
        "tier": "tier2",
        "category": "asian",
        "brand": "Crown",
        "region": "亚洲",
        "is_exchange": 0,
        "note": "皇冠备用线路",
    },
    {
        "company_id": 80,
        "name": "澳门",
        "name_full": "Macau",
        "tier": "tier2",
        "category": "asian",
        "brand": "Macau",
        "region": "亚洲",
        "is_exchange": 0,
        "note": "亚洲盘口传统参考（站方显示为 澳*）",
    },
    {
        "company_id": -2,
        "name": "SBOBET 沙巴",
        "name_full": "SBOBET",
        "tier": "tier2",
        "category": "asian",
        "brand": "SBOBET",
        "region": "亚洲",
        "is_exchange": 0,
        "note": "亚洲高限额公司；站方百家欧赔暂未返回",
    },
    # 中国体彩
    {
        "company_id": 0,
        "name": "中国体育彩票竞彩",
        "name_full": "China Sports Lottery",
        "tier": "china_lottery",
        "category": "lottery",
        "brand": "竞彩",
        "region": "中国",
        "is_exchange": 0,
        "note": "官方玩法，数据存于 jc_odds 表",
    },
]


def sync_companies(conn) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    for row in SEED:
        conn.execute(
            """INSERT INTO odds_companies
               (company_id,name,name_full,tier,category,brand,region,is_exchange,note,updated_at)
               VALUES (:company_id,:name,:name_full,:tier,:category,:brand,:region,
                       :is_exchange,:note,:updated_at)
               ON CONFLICT(company_id) DO UPDATE SET
                 name=excluded.name, name_full=excluded.name_full, tier=excluded.tier,
                 category=excluded.category, brand=excluded.brand, region=excluded.region,
                 is_exchange=excluded.is_exchange, note=excluded.note,
                 updated_at=excluded.updated_at""",
            {**row, "updated_at": now},
        )
    # 把 odds 里出现过的其他公司也建档，tier 留空
    conn.execute(
        """INSERT OR IGNORE INTO odds_companies (company_id, name, updated_at)
           SELECT company_id, MAX(company_name), ? FROM odds GROUP BY company_id""",
        (now,),
    )
    conn.commit()
    return {
        (row[0] or "unclassified"): row[1]
        for row in conn.execute("SELECT tier, COUNT(*) FROM odds_companies GROUP BY tier")
    }
