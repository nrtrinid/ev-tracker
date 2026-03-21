import { cn } from "@/lib/utils";

interface ScannerScopeBarProps {
  books: string[];
  selectedBooks: string[];
  onToggleBook: (book: string) => void;
  bookColors: Record<string, string>;
}

export function ScannerScopeBar({
  books,
  selectedBooks,
  onToggleBook,
  bookColors,
}: ScannerScopeBarProps) {
  return (
    <div>
      <label className="mb-2 block pl-0.5 text-xs font-medium text-muted-foreground">My Books</label>
      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {books.map((book) => {
          const isSelected = selectedBooks.includes(book);
          return (
            <button
              key={book}
              type="button"
              onClick={() => onToggleBook(book)}
              className={cn(
                "whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium transition-all",
                isSelected
                  ? `${bookColors[book] || "bg-foreground"} text-white shadow-md`
                  : "bg-muted text-muted-foreground hover:bg-secondary"
              )}
            >
              {book}
            </button>
          );
        })}
      </div>
    </div>
  );
}
