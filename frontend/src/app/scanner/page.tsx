import { redirect } from "next/navigation";

export default function ScannerIndexPage() {
  // Markets page at / is now the primary surface for scanner discovery
  redirect("/");
}
