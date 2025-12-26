"""
Import script to load bets from CSV into the database.
Run: python import_csv.py path/to/your/file.csv
"""

import csv
import sys
from datetime import datetime
from database import get_db
from calculations import american_to_decimal

# Map CSV "Token" column to promo_type enum values
TOKEN_MAP = {
    "Bonus Bet": "bonus_bet",
    "No-Sweat": "no_sweat",
    "Promo Qual.": "promo_qualifier",
    "Bet Match": "promo_qualifier",  # Bet match is essentially a promo qualifier
    "30% Boost": "boost_30",
    "50% Boost": "boost_50",
    "100% Boost": "boost_100",
    "Standard": "standard",
}

# Map CSV Result to database result
RESULT_MAP = {
    "Win": "win",
    "Lose": "loss",
    "Loss": "loss",
    "Push": "push",
    "Pending": "pending",
    "Void": "void",
    "": "pending",  # Empty = pending
}


def parse_currency(value: str) -> float:
    """Parse currency string like '$10.00' or '-$25.00' to float."""
    if not value or value.strip() == "":
        return 0.0
    # Remove $ and commas, handle negative
    cleaned = value.replace("$", "").replace(",", "").strip()
    if cleaned.startswith("-"):
        return -float(cleaned[1:])
    return float(cleaned)


def parse_percent(value: str) -> float:
    """Parse percent string like '4.50%' to decimal 0.045."""
    if not value or value.strip() == "":
        return 0.0
    return float(value.replace("%", "").strip()) / 100


def parse_date(value: str) -> str | None:
    """Parse date string to ISO format."""
    if not value or value.strip() == "":
        return None
    try:
        # Try different date formats
        for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"]:
            try:
                dt = datetime.strptime(value.strip(), fmt)
                return dt.date().isoformat()
            except ValueError:
                continue
        return None
    except Exception:
        return None


def determine_promo_type(token: str, boost_percent: str) -> tuple[str, float | None]:
    """Determine promo_type and custom boost percent from Token and Boost % columns."""
    token = token.strip()
    
    # Check for custom boost (has a value in boost_percent column)
    if boost_percent and boost_percent.strip():
        try:
            boost_val = float(boost_percent.strip())
            if boost_val > 0:
                # Custom boost percentage
                return "boost_custom", boost_val * 100  # Convert to whole number
        except ValueError:
            pass
    
    # Standard mapping
    promo_type = TOKEN_MAP.get(token, "standard")
    return promo_type, None


def import_csv(filepath: str, dry_run: bool = False):
    """Import bets from CSV file into database."""
    db = get_db()
    
    bets_to_insert = []
    skipped = []
    
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is 1)
            # Skip empty rows
            if not row.get('Date') or not row.get('Sport'):
                skipped.append((row_num, "Empty row"))
                continue
            
            # Skip rows without odds (calculation rows at bottom)
            odds_str = row.get('Odds (American)', '').strip()
            if not odds_str:
                skipped.append((row_num, "No odds"))
                continue
            
            try:
                # Parse core fields
                date_str = parse_date(row.get('Date', ''))
                sport = row.get('Sport', '').strip()
                sportsbook = row.get('Sportsbook', '').strip()
                event = row.get('Event', '').strip() or f"{sport} Game"
                market = row.get('Market', '').strip() or "ML"
                
                # Parse odds
                odds_american = float(odds_str)
                
                # Parse stake
                stake = parse_currency(row.get('Stake ($)', ''))
                if stake <= 0:
                    skipped.append((row_num, f"Invalid stake: {row.get('Stake ($)', '')}"))
                    continue
                
                # Determine promo type
                token = row.get('Token', '').strip()
                boost_percent_str = row.get('Boost % (optional)', '').strip()
                promo_type, boost_percent = determine_promo_type(token, boost_percent_str)
                
                # Parse optional fields
                winnings_cap = parse_currency(row.get('Extra Winnings Cap ($)', ''))
                notes = row.get('Notes', '').strip() or None
                
                # Parse result
                result_str = row.get('Result', '').strip()
                result = RESULT_MAP.get(result_str, "pending")
                
                # Build bet data
                bet_data = {
                    "sport": sport,
                    "event": event,
                    "market": market,
                    "sportsbook": sportsbook,
                    "promo_type": promo_type,
                    "odds_american": odds_american,
                    "stake": stake,
                    "result": result,
                }
                
                # Add optional fields
                if date_str:
                    bet_data["event_date"] = date_str
                    # Use event date as created_at approximation
                    bet_data["created_at"] = f"{date_str}T12:00:00"
                
                if boost_percent:
                    bet_data["boost_percent"] = boost_percent
                
                if winnings_cap > 0:
                    bet_data["winnings_cap"] = winnings_cap
                
                if notes:
                    bet_data["notes"] = notes
                
                # Add settled_at for non-pending bets
                if result != "pending" and date_str:
                    bet_data["settled_at"] = f"{date_str}T18:00:00"
                
                bets_to_insert.append(bet_data)
                
            except Exception as e:
                skipped.append((row_num, f"Error: {str(e)}"))
                continue
    
    print(f"\n{'='*50}")
    print(f"CSV Import Summary")
    print(f"{'='*50}")
    print(f"Bets to import: {len(bets_to_insert)}")
    print(f"Rows skipped:   {len(skipped)}")
    
    if skipped:
        print(f"\nSkipped rows:")
        for row_num, reason in skipped[:10]:  # Show first 10
            print(f"  Row {row_num}: {reason}")
        if len(skipped) > 10:
            print(f"  ... and {len(skipped) - 10} more")
    
    # Show sample of what will be imported
    if bets_to_insert:
        print(f"\nSample bets to import:")
        for bet in bets_to_insert[:3]:
            print(f"  {bet['event_date'] if 'event_date' in bet else 'No date'} | "
                  f"{bet['sportsbook']} | {bet['promo_type']} | "
                  f"{bet['odds_american']:+.0f} | ${bet['stake']:.2f} | {bet['result']}")
        if len(bets_to_insert) > 3:
            print(f"  ... and {len(bets_to_insert) - 3} more")
    
    if dry_run:
        print(f"\n[DRY RUN] No data was inserted. Run without --dry-run to import.")
        return 0
    
    # Insert into database
    print(f"\nInserting {len(bets_to_insert)} bets...")
    try:
        result = db.table("bets").insert(bets_to_insert).execute()
        inserted = len(result.data) if result.data else 0
        print(f"✓ Successfully inserted {inserted} bets!")
        return inserted
    except Exception as e:
        print(f"✗ Error inserting bets: {e}")
        return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python import_csv.py <path_to_csv> [--dry-run]")
        print("\nOptions:")
        print("  --dry-run    Preview import without actually inserting data")
        print("\nExample:")
        print("  python import_csv.py 'C:\\Users\\gertr\\Downloads\\Bet Spreadsheet - Bets.csv'")
        sys.exit(1)
    
    filepath = sys.argv[1]
    dry_run = "--dry-run" in sys.argv
    
    print(f"Importing from: {filepath}")
    if dry_run:
        print("Mode: DRY RUN (no data will be inserted)")
    
    import_csv(filepath, dry_run=dry_run)

