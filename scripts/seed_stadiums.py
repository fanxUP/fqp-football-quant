"""Idempotently seed stadium coordinates for weather/travel features."""

from typing import Any

from apps.backend.src.db import get_db

STADIUMS = [
    # 2026 World Cup neutral venues present in the official Sporttery remarks
    ("SoFi Stadium", "Inglewood", "United States", 33.9535, -118.3392, 70240),
    ("Hard Rock Stadium", "Miami Gardens", "United States", 25.9580, -80.2389, 65326),
    ("Arrowhead Stadium", "Kansas City", "United States", 39.0489, -94.4839, 76416),
    ("MetLife Stadium", "East Rutherford", "United States", 40.8128, -74.0742, 82500),
    # Norway Eliteserien
    ("Aker Stadion", "Molde", "Norway", 62.7334, 7.1481, 11249),
    ("SR-Bank Arena", "Stavanger", "Norway", 58.9146, 5.7304, 15900),
    # Swedish Allsvenskan
    ("Studenternas IP", "Uppsala", "Sweden", 59.8400, 17.6500, 10000),
    ("Tele2 Arena", "Stockholm", "Sweden", 59.2900, 18.0850, 30000),
    ("Friends Arena", "Solna", "Sweden", 59.3725, 18.0003, 50000),
    ("Gamla Ullevi", "Gothenburg", "Sweden", 57.7060, 11.9800, 18416),
    ("Boras Arena", "Boras", "Sweden", 57.7340, 12.9350, 16899),
    ("Strandvallen", "Hallevik", "Sweden", 56.0330, 14.6000, 7500),
    ("Eleda Stadion", "Malmo", "Sweden", 55.5830, 12.9830, 22500),
    ("Stora Valla", "Degerfors", "Sweden", 59.3300, 14.5200, 7500),
    ("Guldfageln Arena", "Kalmar", "Sweden", 56.6900, 16.3200, 12182),
    ("Behrn Arena", "Orebro", "Sweden", 59.2670, 15.2150, 12645),
    ("Bravida Arena", "Gothenburg", "Sweden", 57.7230, 11.9330, 6500),
    ("Olympia", "Helsingborg", "Sweden", 56.0480, 12.7000, 16500),
    ("Orjans Vall", "Halmstad", "Sweden", 56.6745, 12.8569, 10873),
    ("Grimsta IP", "Stockholm", "Sweden", 59.3623, 17.8518, 6820),
    # K League 1
    ("Jeonju World Cup Stadium", "Jeonju", "South Korea", 35.8680, 127.0650, 42477),
    ("Seoul World Cup Stadium", "Seoul", "South Korea", 37.5680, 126.8970, 66704),
    ("Ulsan Munsu Stadium", "Ulsan", "South Korea", 35.5350, 129.2600, 44102),
    ("Daejeon World Cup Stadium", "Daejeon", "South Korea", 36.3660, 127.3250, 40535),
    ("Gwangju World Cup Stadium", "Gwangju", "South Korea", 35.1320, 126.8750, 40245),
    ("Pohang Steel Yard", "Pohang", "South Korea", 36.0060, 129.3840, 17443),
    ("Jeju World Cup Stadium", "Seogwipo", "South Korea", 33.2460, 126.5090, 35657),
    ("Incheon Football Stadium", "Incheon", "South Korea", 37.4660, 126.6430, 20891),
    ("Anyang Sports Complex", "Anyang", "South Korea", 37.3950, 126.9520, 18000),
    ("Bucheon Stadium", "Bucheon", "South Korea", 37.5247, 126.7897, 34182),
    ("Gimcheon Stadium", "Gimcheon", "South Korea", 36.1290, 128.0860, 25000),
    ("Gangneung Stadium", "Gangneung", "South Korea", 37.7700, 128.9000, 22333),
    # Finland Veikkausliiga
    ("Bolt Arena", "Helsinki", "Finland", 60.1870, 24.9220, 10770),
    ("Veritas Stadion", "Turku", "Finland", 60.4430, 22.2920, 9372),
    ("Raatin Stadion", "Oulu", "Finland", 65.0160, 25.4700, 4392),
    ("Kuopion Keskuskentta", "Kuopio", "Finland", 62.8900, 27.6700, 5000),
    ("Lahden Stadion", "Lahti", "Finland", 60.9830, 25.6340, 14500),
    ("Tammelan Stadion", "Tampere", "Finland", 61.5000, 23.7700, 5040),
    ("Wiklof Holding Arena", "Mariehamn", "Finland", 60.1000, 19.9450, 4500),
    ("Hietalahti Stadium", "Vaasa", "Finland", 63.0950, 21.6170, 4600),
    ("Seinajoen Keskuskentta", "Seinajoki", "Finland", 62.7900, 22.8400, 5000),
    ("Project Liv Arena", "Pietarsaari", "Finland", 63.6743, 22.7029, 5000),
    # Current Norwegian league venues verified from the official fixture list
    ("Brann stadion", "Bergen", "Norway", 60.3668, 5.3574, 16686),
    ("Sarpsborg st KG", "Sarpsborg", "Norway", 59.2863, 11.0977, 8022),
    ("KFUM-Arena", "Oslo", "Norway", 59.8896, 10.7831, 3300),
    ("Jotun Arena", "Sandefjord", "Norway", 59.1372, 10.1795, 6582),
    ("Color Line Stadion", "Alesund", "Norway", 62.4697, 6.1886, 10778),
    ("Lerkendal stadion", "Trondheim", "Norway", 63.4123, 10.4045, 21423),
    ("Aspmyra stadion", "Bodo", "Norway", 67.2766, 14.3844, 8270),
    ("Briskeby", "Hamar", "Norway", 60.7956, 11.0922, 7600),
    ("Intility Arena", "Oslo", "Norway", 59.9179, 10.8066, 16555),
    ("Fredrikstad stadion", "Fredrikstad", "Norway", 59.2131, 10.9281, 12565),
    ("Mustapekka Areena", "Helsinki", "Finland", 60.2347, 24.9625, 1100),
    ("Strawberry Arena", "Solna", "Sweden", 59.3725, 18.0017, 50000),
    # International / World Cup
    ("Lusail Stadium", "Lusail", "Qatar", 25.4200, 51.4900, 88966),
    ("Al Bayt Stadium", "Al Khor", "Qatar", 25.6520, 51.4880, 68895),
    ("Khalifa International Stadium", "Doha", "Qatar", 25.2644, 51.4483, 45857),
    ("Education City Stadium", "Al Rayyan", "Qatar", 25.3100, 51.4240, 45350),
    ("Al Janoub Stadium", "Al Wakrah", "Qatar", 25.1580, 51.5740, 44325),
    ("Ahmad bin Ali Stadium", "Al Rayyan", "Qatar", 25.3310, 51.3410, 45032),
    ("Stadium 974", "Doha", "Qatar", 25.2890, 51.5660, 44089),
    # Major European national team stadiums
    ("Wembley Stadium", "London", "England", 51.5560, -0.2790, 90000),
    ("Stade de France", "Saint-Denis", "France", 48.9245, 2.3600, 81338),
    ("Estadio Nacional", "Brasilia", "Brazil", -15.7801, -47.9292, 72788),
    ("Maracana", "Rio de Janeiro", "Brazil", -22.9120, -43.2300, 78838),
    ("Arena do Grêmio", "Porto Alegre", "Brazil", -29.9734, -51.1944, 60540),
    ("MorumBIS", "Sao Paulo", "Brazil", -23.6001, -46.7201, 66795),
    ("Soccer City", "Johannesburg", "South Africa", -26.2347, 27.9825, 94736),
]

TEAM_STADIUM_CITIES = {
    "莫尔德": "Molde",
    "维京": "Stavanger",
    "瓦萨": "Vaasa",
    "塞伊奈约基": "Seinajoki",
    "富川FC": "Bucheon",
    "安养FC": "Anyang",
    "大田市民": "Daejeon",
    "光州FC": "Gwangju",
    "浦项制铁": "Pohang",
    "金泉尚武": "Gimcheon",
    "蔚山现代": "Ulsan",
    "全北现代": "Jeonju",
    "仁川联": "Incheon",
    "济州SK": "Seogwipo",
    "首尔FC": "Seoul",
    "江原FC": "Gangneung",
    "哈尔姆斯塔德": "Halmstad",
    "哈马比": "Stockholm",
    "埃尔夫斯堡": "Boras",
    "雅罗": "Pietarsaari",
    "TPS图尔库": "Turku",
    "TPS土尔库": "Turku",
    "玛丽港": "Mariehamn",
    "卡尔马": "Kalmar",
    "厄尔格里特": "Gothenburg",
}

# Exact mappings take precedence over legacy city mappings. This matters in
# cities with several stadiums (for example Gothenburg and Stockholm).
TEAM_STADIUM_NAMES = {
    "布鲁马波卡纳": "Grimsta IP",
    "天狼星": "Studenternas IP",
    "国际图尔库": "Veritas Stadion",
    "坦佩雷山猫": "Tammelan Stadion",
    "布兰": "Brann stadion",
    "赫尔辛基": "Bolt Arena",
    "哥德堡盖斯": "Gamla Ullevi",
    "马尔默": "Eleda Stadion",
    "萨尔普斯堡": "Sarpsborg st KG",
    "奥斯陆KFUM": "KFUM-Arena",
    "桑纳菲尤尔": "Jotun Arena",
    "奥勒松": "Color Line Stadion",
    "弗拉门戈": "Maracana",
    "格雷米奥": "Arena do Grêmio",
    "赫根": "Bravida Arena",
    "罗森博格": "Lerkendal stadion",
    "博德闪耀": "Aspmyra stadion",
    "汉坎": "Briskeby",
    "瓦勒伦加": "Intility Arena",
    "腓特烈斯塔": "Fredrikstad stadion",
    "赫尔辛基火花": "Mustapekka Areena",
    "AIK索尔纳": "Strawberry Arena",
    "圣保罗": "MorumBIS",
    "弗鲁米嫩塞": "Maracana",
    "拉赫蒂": "Lahden Stadion",
    "IFK哥德堡": "Gamla Ullevi",
}


def run() -> dict[str, Any]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM stadiums")
            before = cur.fetchone()[0]
            inserted = 0
            for name, city, country, lat, lon, capacity in STADIUMS:
                try:
                    cur.execute(
                        """
                        INSERT INTO stadiums (
                            stadium_name, city, country, latitude, longitude, capacity,
                            pitch_type, data_source, data_confidence
                        )
                        SELECT %s, %s, %s, %s, %s, %s, 'grass', 'curated_reference', 0.9
                        WHERE NOT EXISTS (
                            SELECT 1 FROM stadiums
                            WHERE stadium_name = %s AND city = %s AND country = %s
                        )
                        """,
                        (name, city, country, lat, lon, capacity, name, city, country),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as e:
                    print(f"  skip {name}: {e}")
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM stadiums")
            after = cur.fetchone()[0]
            print(f"Stadiums: {before} → {after} (inserted {inserted})")

            history_inserted = 0
            for team_name, city in TEAM_STADIUM_CITIES.items():
                cur.execute(
                    """
                    SELECT t.id, s.id
                    FROM teams t
                    JOIN team_aliases ta ON ta.team_id = t.id
                    JOIN stadiums s ON s.city = %s
                    WHERE ta.alias_name = %s AND ta.source_name = 'sporttery'
                    ORDER BY t.id, s.id
                    LIMIT 1
                    """,
                    (city, team_name),
                )
                row = cur.fetchone()
                if not row:
                    continue
                cur.execute(
                    """
                    INSERT INTO team_stadium_history
                        (team_id, stadium_id, start_date, is_primary, is_temporary)
                    SELECT %s, %s, DATE '2020-01-01', true, false
                    WHERE NOT EXISTS (
                        SELECT 1 FROM team_stadium_history
                        WHERE team_id = %s AND stadium_id = %s AND is_primary = true
                    )
                    """,
                    (row[0], row[1], row[0], row[1]),
                )
                history_inserted += cur.rowcount
                cur.execute(
                    """
                    UPDATE teams
                    SET primary_stadium_id = COALESCE(primary_stadium_id, %s),
                        updated_at = now()
                    WHERE id = %s
                    """,
                    (row[1], row[0]),
                )

            for team_name, stadium_name in TEAM_STADIUM_NAMES.items():
                cur.execute(
                    """
                    SELECT t.id, s.id
                    FROM teams t
                    JOIN team_aliases ta ON ta.team_id = t.id
                    JOIN stadiums s ON s.stadium_name = %s
                    WHERE ta.alias_name = %s AND ta.source_name = 'sporttery'
                    ORDER BY t.id, s.id
                    LIMIT 1
                    """,
                    (stadium_name, team_name),
                )
                row = cur.fetchone()
                if not row:
                    continue
                cur.execute(
                    """
                    INSERT INTO team_stadium_history
                        (team_id, stadium_id, start_date, is_primary, is_temporary)
                    SELECT %s, %s, DATE '2026-01-01', true, false
                    WHERE NOT EXISTS (
                        SELECT 1 FROM team_stadium_history
                        WHERE team_id = %s AND stadium_id = %s AND is_primary = true
                    )
                    """,
                    (row[0], row[1], row[0], row[1]),
                )
                history_inserted += cur.rowcount
                cur.execute(
                    """
                    UPDATE teams
                    SET primary_stadium_id = %s, updated_at = now()
                    WHERE id = %s
                    """,
                    (row[1], row[0]),
                )
            conn.commit()
            print(f"Team stadium mappings inserted: {history_inserted}")
            cur.execute("SELECT COUNT(*) FROM team_stadium_history")
            mappings_total = int(cur.fetchone()[0])

    return {
        "status": "ok" if mappings_total > 0 else "blocked",
        "stadiums_before": before,
        "stadiums_after": after,
        "stadiums_inserted": inserted,
        "mappings_inserted": history_inserted,
        "mappings_total": mappings_total,
        "message": None if mappings_total > 0 else "waiting for official team registry",
    }


if __name__ == "__main__":
    run()
