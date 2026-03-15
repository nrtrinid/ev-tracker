"""
Seed script to populate database with mock betting data.
Run this to test analytics/charts with realistic data.
"""

import random
from datetime import datetime, timedelta
from database import get_db
from calculations import american_to_decimal

# Realistic data pools
SPORTSBOOKS = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN Bet", "Fanatics"]
SPORTS = ["NFL", "NBA", "MLB", "NHL", "NCAAF", "NCAAB", "UFC"]
MARKETS = ["ML", "Spread", "Total", "SGP", "Prop"]
PROMO_TYPES = ["standard", "bonus_bet", "no_sweat", "promo_qualifier", "boost_30", "boost_50", "boost_100"]
RESULTS = ["win", "loss", "push"]

# Team/event names by sport
TEAMS = {
    "NFL": ["Chiefs", "Bills", "49ers", "Ravens", "Cowboys", "Eagles"],
    "NBA": ["Lakers", "Celtics", "Bucks", "Nuggets", "Warriors", "Heat"],
    "MLB": ["Yankees", "Dodgers", "Astros", "Braves", "Mets", "Red Sox"],
    "NHL": ["Avalanche", "Lightning", "Bruins", "Rangers", "Oilers", "Panthers"],
    "NCAAF": ["Alabama", "Georgia", "Ohio State", "Michigan", "Texas", "USC"],
    "NCAAB": ["Duke", "UNC", "Kansas", "Kentucky", "Villanova", "Gonzaga"],
    "UFC": ["Main Event", "Co-Main", "Prelims"],
}

def generate_odds(promo_type=None):
    """Generate realistic American odds tuned to promo strategy."""
    # Bonus bets: maximize upside, target +300 to +500 with a small long-tail
    if promo_type == "bonus_bet":
        r = random.random()
        if r < 0.70:
            return random.randint(300, 500)
        elif r < 0.90:
            return random.randint(200, 299)
        else:
            return random.randint(501, 600)

    # No-sweats / qualifiers: insured leg, but still prefer plus-money with moderate tails
    if promo_type in {"no_sweat", "promo_qualifier"}:
        r = random.random()
        if r < 0.60:
            return random.randint(180, 320)
        elif r < 0.85:
            return random.randint(321, 450)
        else:
            return random.randint(-120, 179)  # occasional smaller favorite to reduce variance

    # Boosts: best value in mid dogs; allow some longer shots
    if promo_type and promo_type.startswith("boost"):
        r = random.random()
        if r < 0.60:
            return random.randint(200, 350)
        elif r < 0.85:
            return random.randint(351, 500)
        else:
            return random.randint(150, 199)

    # Standard bets: realistic mix near even, slight dog lean
    r = random.random()
    if r < 0.25:
        return random.randint(-150, -101)  # Small favorites
    elif r < 0.50:
        return random.randint(100, 150)    # Small underdogs
    elif r < 0.75:
        return random.randint(151, 250)
    else:
        return random.randint(-250, -151)

def generate_stake(promo_type):
    """Generate realistic stake based on promo type."""
    if promo_type == "promo_qualifier":
        # Promo qualifiers are rare high stakes (almost never $100)
        return random.choices([50, 100], weights=[90, 10], k=1)[0]
    elif promo_type == "no_sweat":
        # No sweats occasionally higher ($25/$50, rarely $50)
        return random.choices([10, 25, 50], weights=[40, 45, 15], k=1)[0]
    elif promo_type in ["bonus_bet"]:
        # Bonus bets are fixed promo amounts
        return random.choices([10, 25, 50], weights=[60, 30, 10], k=1)[0]
    else:
        # Regular bets and boosts: mostly $10, some $25, rare $50
        return random.choices([10, 25, 50], weights=[75, 20, 5], k=1)[0]

def generate_event_name(sport, market):
    """Generate realistic event name."""
    teams = TEAMS.get(sport, ["Team A", "Team B"])
    team = random.choice(teams)
    
    if market == "ML":
        return team
    elif market == "Spread":
        spread = random.choice([-7.5, -6.5, -3.5, -2.5, -1.5, 1.5, 2.5, 3.5, 6.5, 7.5])
        return f"{team} {spread:+.1f}"
    elif market == "Total":
        total = random.choice([45.5, 47.5, 50.5, 52.5, 55.5, 220.5, 225.5])
        direction = random.choice(["Over", "Under"])
        return f"{direction} {total}"
    elif market == "SGP":
        return f"{team} SGP"
    else:  # Prop
        props = [f"{team} 1H", f"{team} TT", f"Player Props"]
        return random.choice(props)

def generate_mock_bets(num_bets=100):
    """Generate mock betting data with realistic date clustering."""
    db = get_db()
    
    # Date range: last 60 days
    end_date = datetime.now()
    start_date = end_date - timedelta(days=60)
    
    # Create realistic betting days (cluster bets on certain days, gaps on others)
    betting_days = []
    current = start_date
    while current <= end_date - timedelta(days=7):  # Leave last week for pending bets
        # 60% chance of betting on any given day
        if random.random() < 0.6:
            # 1-5 bets per active day
            num_bets_this_day = random.choices([1, 2, 3, 4, 5], weights=[30, 35, 20, 10, 5], k=1)[0]
            for _ in range(num_bets_this_day):
                # Add some time variation within the day
                bet_time = current + timedelta(hours=random.randint(10, 23), minutes=random.randint(0, 59))
                betting_days.append(bet_time)
        current += timedelta(days=1)
    
    # Ensure we have enough betting days, if not add more
    while len(betting_days) < num_bets:
        random_day = start_date + timedelta(days=random.randint(0, 53))
        random_time = random_day + timedelta(hours=random.randint(10, 23), minutes=random.randint(0, 59))
        betting_days.append(random_time)
    
    # Shuffle and limit to requested number (settled bets only in main loop)
    random.shuffle(betting_days)
    num_settled = int(num_bets * 0.9)
    betting_days = sorted(betting_days[:num_settled])
    
    bets = []
    
    # Generate settled bets with realistic date clustering
    for i, created_at in enumerate(betting_days):
        # Weighted promo type selection (bonus_bet most common)
        promo_type = random.choices(
            PROMO_TYPES,
            weights=[15, 40, 10, 10, 8, 8, 9],  # Bonus bets most common
            k=1
        )[0]
        
        sport = random.choice(SPORTS)
        market = random.choice(MARKETS)
        sportsbook = random.choice(SPORTSBOOKS)
        odds_american = generate_odds(promo_type)
        stake = generate_stake(promo_type)
        
        # Determine result based on implied probability from odds
        decimal_odds = american_to_decimal(odds_american)
        implied_prob = 1 / decimal_odds
        
        # Wins occur at approximately implied probability
        # (slightly less due to vig, but close enough for mock data)
        if random.random() < implied_prob:
            result = "win"
        elif random.random() < 0.98:  # 2% push rate
            result = "loss"
        else:
            result = "push"
        
        # Event happens 2-12 hours after bet placement
        event_date = created_at + timedelta(hours=random.randint(2, 12))
        settled_at = event_date + timedelta(hours=random.randint(1, 4))
        
        bet_data = {
            "sport": sport,
            "event": generate_event_name(sport, market),
            "market": market,
            "sportsbook": sportsbook,
            "promo_type": promo_type,
            "odds_american": odds_american,
            "stake": stake,
            "result": result,
            "event_date": event_date.date().isoformat(),
            "created_at": created_at.isoformat(),
            "settled_at": settled_at.isoformat(),
        }
        
        # Add boost percent for boost types
        if promo_type == "boost_custom":
            bet_data["boost_percent"] = random.choice([25, 33, 40, 50, 75])
        
        # Occasionally add winnings cap for boosts
        if promo_type.startswith("boost") and random.random() < 0.2:
            bet_data["winnings_cap"] = random.choice([25, 50, 100, 250])
        
        # Add notes to some bets
        if random.random() < 0.15:
            notes = [
                "Sharp line",
                "Line moved quickly",
                "Hedge opportunity",
                "CLV positive",
                "Late bet",
                "Limit increased",
            ]
            bet_data["notes"] = random.choice(notes)
        
        bets.append(bet_data)
    
    # Add pending bets (10% of total)
    num_pending = int(num_bets * 0.1)
    for _ in range(num_pending):
        promo_type = random.choices(PROMO_TYPES, weights=[15, 40, 10, 10, 8, 8, 9], k=1)[0]
        sport = random.choice(SPORTS)
        market = random.choice(MARKETS)
        sportsbook = random.choice(SPORTSBOOKS)
        odds_american = generate_odds(promo_type)
        stake = generate_stake(promo_type)
        
        # Recent pending bets
        created_at = end_date - timedelta(days=random.randint(0, 5), hours=random.randint(0, 23))
        event_date = created_at + timedelta(days=random.randint(0, 7))
        
        bet_data = {
            "sport": sport,
            "event": generate_event_name(sport, market),
            "market": market,
            "sportsbook": sportsbook,
            "promo_type": promo_type,
            "odds_american": odds_american,
            "stake": stake,
            "result": "pending",
            "event_date": event_date.date().isoformat(),
            "created_at": created_at.isoformat(),
        }
        
        if promo_type == "boost_custom":
            bet_data["boost_percent"] = random.choice([25, 33, 40, 50, 75])
        
        bets.append(bet_data)
    
    # Insert all bets
    try:
        result = db.table("bets").insert(bets).execute()
        return len(result.data) if result.data else 0
    except Exception as e:
        print(f"Error inserting bets: {e}")
        return 0

def clear_existing_data():
    """Clear all existing bets (optional - use with caution!)."""
    db = get_db()
    try:
        # Delete all bets
        result = db.table("bets").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        return True
    except Exception as e:
        print(f"Error clearing data: {e}")
        return False

if __name__ == "__main__":
    import sys
    
    print("EV Tracker - Database Seeding Script")
    print("=" * 50)
    
    # Check if user wants to clear existing data
    if "--clear" in sys.argv:
        confirm = input("⚠️  This will DELETE all existing bets. Are you sure? (yes/no): ")
        if confirm.lower() == "yes":
            print("Clearing existing data...")
            if clear_existing_data():
                print("✓ Existing data cleared")
            else:
                print("✗ Failed to clear data")
                sys.exit(1)
        else:
            print("Cancelled.")
            sys.exit(0)
    
    # Get number of bets to generate
    num_bets = 100
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        num_bets = int(sys.argv[1])
    
    print(f"\nGenerating {num_bets} mock bets...")
    inserted = generate_mock_bets(num_bets)
    
    print(f"✓ Successfully inserted {inserted} bets")
    print("\nData breakdown:")
    print("  - Time range: Last 60 days")
    print("  - ~90% settled, ~10% pending")
    print("  - ~30% win rate (realistic for +EV)")
    print("  - Mixed sportsbooks and promo types")
    print("\n🎯 Open /analytics to see the charts!")
