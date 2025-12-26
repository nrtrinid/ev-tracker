"""
Quick script to clear all bets from the database.
Run: python clear_bets.py
"""

from database import get_db

def clear_all_bets():
    """Delete all bets from the database."""
    db = get_db()
    
    try:
        # Delete all bets (using a condition that matches all rows)
        result = db.table("bets").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        print("✓ All bets cleared successfully!")
        return True
    except Exception as e:
        print(f"✗ Error clearing bets: {e}")
        return False

if __name__ == "__main__":
    import sys
    
    # Allow --yes flag to skip confirmation
    if "--yes" in sys.argv:
        clear_all_bets()
    else:
        confirm = input("WARNING: This will DELETE ALL bets from the database. Are you sure? (yes/no): ")
        if confirm.lower() == "yes":
            clear_all_bets()
        else:
            print("Cancelled.")

