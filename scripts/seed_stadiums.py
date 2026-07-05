"""One-shot script to seed basic stadium data for weather/travel features."""
from apps.backend.src.db import get_db

STADIUMS = [
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
    ("Soccer City", "Johannesburg", "South Africa", -26.2347, 27.9825, 94736),
]

def run():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM stadiums")
            before = cur.fetchone()[0]
            inserted = 0
            for name, city, country, lat, lon, capacity in STADIUMS:
                try:
                    cur.execute("""
                        INSERT INTO stadiums (stadium_name, city, country, latitude, longitude, capacity, surface_type)
                        VALUES (%s, %s, %s, %s, %s, %s, 'grass')
                        ON CONFLICT DO NOTHING
                    """, (name, city, country, lat, lon, capacity))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as e:
                    print(f"  skip {name}: {e}")
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM stadiums")
            after = cur.fetchone()[0]
            print(f"Stadiums: {before} → {after} (inserted {inserted})")

if __name__ == "__main__":
    run()
